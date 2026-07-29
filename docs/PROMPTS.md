# Prompts, Models and Keys

Every LLM call this project makes: what the prompt is, which model answers it,
and which API key pays for it.

Verified against the running system on 2026-07-29.

---

## 1. Providers and keys

Five providers are wired. All are free-tier by design; the router falls through
on rate limits rather than failing.

| Provider | Endpoint | Key (`.env`) | Configured now |
|---|---|---|---|
| OpenRouter | `openrouter.ai/api/v1/chat/completions` | `OPENROUTER_API_KEY` | set |
| Nvidia NIM | `integrate.api.nvidia.com/v1/chat/completions` | `NVIDIA_API_KEY` | set |
| SambaNova | `api.sambanova.ai/v1/chat/completions` | `SAMBANOVA_API_KEY` | set |
| GitHub Models | `models.inference.ai.azure.com/chat/completions` | `GITHUB_MODELS_TOKEN` | set |
| Anthropic | `api.anthropic.com` | `ANTHROPIC_API_KEY` | empty — opt-in override, see §5 |

### Model names in force

Defaults live in `config.py`; `.env` overrides them. Current values:

| Setting | Value | Provider |
|---|---|---|
| `OPENROUTER_PRIMARY_MODEL` | `nvidia/nemotron-3-ultra-550b-a55b:free` | OpenRouter |
| `OPENROUTER_FALLBACK_MODEL` | `nvidia/nemotron-3-super-120b-a12b:free` | OpenRouter |
| `NVIDIA_FALLBACK_MODEL` | `meta/llama-3.1-405b-instruct` | Nvidia NIM |
| `NVIDIA_BACKUP_MODEL` | `meta/llama-3.3-70b-instruct` | Nvidia NIM |
| `SAMBANOVA_MODEL` | `Meta-Llama-3.3-70B-Instruct` | SambaNova |
| `GITHUB_MODELS_MODEL` | `Llama-3.3-70B-Instruct` | GitHub Models |
| `ANTHROPIC_MODEL` | `claude-sonnet-5` | Anthropic (unused) |

These are also the shipped defaults. `Config.__init__` used to pass
`os.getenv(..., "anthropic/claude-sonnet-4.5")`, whose literal always beat the
free defaults declared on `AIConfig` — so anyone who copied `.env.example` and
added only an OpenRouter key was billed for Claude. It now reads
`os.getenv(...) or AIConfig.<field>`, making the dataclass the single source and
the free model the default.

---

## 2. The router: `agent/llm_client.py`

`ModelRouter` walks an ordered chain and falls through on rate limits or errors.
`config.get_tier_chain(task_shape)` builds it. Only tiers whose key is present
are included.

**`task_shape="quick"`** — short prompts, latency matters:

```
1. SambaNova       Meta-Llama-3.3-70B-Instruct        SAMBANOVA_API_KEY
2. OpenRouter      nemotron-3-ultra-550b-a55b:free    OPENROUTER_API_KEY
3. OpenRouter      nemotron-3-super-120b-a12b:free    OPENROUTER_API_KEY
4. Nvidia NIM      meta/llama-3.1-405b-instruct       NVIDIA_API_KEY
5. Nvidia NIM      meta/llama-3.3-70b-instruct        NVIDIA_API_KEY
```

**`task_shape="deep"`** — long context, multi-section output:

```
1. GitHub Models   Llama-3.3-70B-Instruct  (128K ctx)  GITHUB_MODELS_TOKEN
2. OpenRouter      nemotron-3-ultra-550b-a55b:free     OPENROUTER_API_KEY
3. OpenRouter      nemotron-3-super-120b-a12b:free     OPENROUTER_API_KEY
4. Nvidia NIM      meta/llama-3.1-405b-instruct        NVIDIA_API_KEY
5. Nvidia NIM      meta/llama-3.3-70b-instruct         NVIDIA_API_KEY
6. SambaNova       Meta-Llama-3.3-70B-Instruct         SAMBANOVA_API_KEY
```

SambaNova appears at both ends of the deep chain: it is a separate free quota
pool from OpenRouter and NIM, so it is worth keeping as a last resort. When
every tier is exhausted the router raises `AllTiersExhausted` and the UI says so
plainly rather than degrading silently.

A tier that 429s or 404s is put on a cooldown (300s for a quota hit) so it
doesn't cost a guaranteed-fail round trip on the next request. Self-healing —
no config edit needed.

**Anthropic sits outside the chain.** `chat()` and `tool_use_loop()` try it
*first* when `ANTHROPIC_API_KEY` is set, falling through to the free chain if it
errors. `stream()` deliberately skips it — different wire format, and the
conversational path is free-chain by design. So setting that key changes
`/api/ai` and the deep dive but not the streaming analyst.

### `complete()` — the sync entry point

`agent/llm_client.py::complete(system, user, task_shape)` runs one exchange
through the router from synchronous code and returns `""` on total failure
rather than raising. Services that need a single completion use this; it is what
replaced their hand-rolled provider ladders.

---

## 3. Prompts that go through the router

### 3.1 Conversational analyst — `agent/chat.py`

The main one. `build_system(intent, data_blocks)` assembles
`_STYLE` + intent steer + a `=== DATA ===` block, then history, then the
question.

- **Called by:** `/api/ai/stream` (the AI Analyst page) and `/api/ai`
- **`_STYLE`** — the shared contract. Grounding rules: every number must come
  from the data block; no invented intraday figures; no sources named that
  aren't in the data; a close is a close, not a live price; deterministic engine
  output is presented verbatim, never re-derived. Plus house style and the SEBI
  compliance boundary (soft signals only, never buy/sell).
- **`_INTENT_STEER[...]`** — six task instructions selected by the router:

| Intent | Steer | task_shape |
|---|---|---|
| `lookup` | answer the one question, briefly, no report | `quick` |
| `screen` | answer only from the constituent table; output no table of your own | `deep` |
| `compare` | side-by-side table, then what the differences mean | `deep` |
| `portfolio` | this user's real book — actual symbols, weights, P&L | `deep` |
| `deep` | 8 fixed sections, reproduce every red flag and sub-score | `deep` |
| `market` | answer from the live snapshot and web results | `quick` |

### 3.2 Market brief — `api/server.py::_brief`

- **Called by:** `/api/brief`, the dashboard's daily round-up. Cached 15 min.
- **Prompt:** a bullet-list spec — Headline, Under the surface, Sectors, Movers,
  Money flows, Global cues, Watch next — in plain English for a non-professional
  reader, with the live market snapshot inlined as the only source of fact.
- **task_shape:** `deep`. It was `quick`; the small models dropped sections and
  invented numbers when holding this much context.

### 3.3 Deep-dive tool loop — `agent/orchestration.py` + `agent/prompts.py`

- **Called by:** `/api/ai` when the intent is `deep`, via `run_analysis_sync`.
- **Prompt:** `build_prompt(analysis_type)` = `BASE_SYSTEM_PROMPT` + one task
  prompt. `BASE_SYSTEM_PROMPT` is the citation-constrained contract: never emit
  a number without calling a tool, annotate every bullet with its source, no
  external knowledge, present the deterministic engines faithfully.
- **Task prompts:** `DEEP_DIVE_PROMPT`, `SWOT_PROMPT`, `VERDICT_PROMPT`,
  `SECTOR_OUTLOOK_PROMPT` (`analysis_type` selects; defaults to deep dive).
- **task_shape:** `deep`, with the tool schemas attached.

### 3.4 Bull / Bear / Judge debate — `agent/debate.py`

Three sequential calls at `task_shape="quick"`, all fed the *already-computed*
red-flag and scorecard findings — the debate never calls the tools itself.

| Call | System prompt |
|---|---|
| `_BULL_SYSTEM` | strongest data-grounded constructive case, 2-4 bullets, no number not in the findings |
| `_BEAR_SYSTEM` | strongest data-grounded case for caution, same constraint |
| `_JUDGE_SYSTEM` | balanced 2-3 sentence verdict; may only soften language, cannot change any number or severity; ends on a soft signal |

The score shown to the user is taken from the findings, never from the judge's
text.

---

## 4. Service prompts

Five services each make one grounded completion. All go through `complete()`, so
all get the full tier chain and its cooldowns.

| Service | Prompt | Shape |
|---|---|---|
| `services/stock_analysis_llm.py` | "rigorous, grounded equity analyst; never fabricate numbers, never give direct buy/sell advice" → 5-section stock read | `deep` |
| `services/fno_narrative.py` | `_SYSTEM` — "rigorous, grounded senior F&O/derivatives strategist for Indian index options" → 5-section option-chain read | `deep` |
| `services/market_news.py` | "financial news editor for Indian markets; rank and summarise search results; never fabricate facts, headlines or URLs" | `quick` |
| `services/market_events.py` | "extract scheduled economic events from search results; return ONLY a JSON array; never invent events or dates" | `quick` |
| `services/breadth.py` | "senior Indian equity market strategist; exactly two sentences on today's internals" | `quick` |

Until this was consolidated, each of these POSTed to a provider directly with a
hardcoded model and its own retry ladder. Four were NIM-only, so they returned
nothing whenever NIM was rate-limited even with four other tiers idle;
`fno_narrative` was the only one that crossed providers. `tests/
test_llm_routing_consistency.py` fails if a direct provider URL reappears in any
of them.

All five degrade honestly when `complete()` returns `""` — `breadth` falls back
to its deterministic breadth line, the others report `ok: False` and the UI
shows the underlying data without commentary.

---

## 5. Design notes and remaining caveats

**Anthropic is an opt-in override, not a chain member.** `get_tier_chain()` has
no Anthropic branch, but `ModelRouter.chat()` and `tool_use_loop()` both try
`self.anthropic` ahead of the chain when `ANTHROPIC_API_KEY` is set, falling
through on error. `stream()` skips it deliberately (documented in its
docstring): different wire format, and the conversational path is free-chain by
design. Consequence worth knowing — setting that key changes `/api/ai` and the
deep dive, but the streaming analyst stays on the free chain.

**One grounding contract, composed twice.** `agent/prompts.py::GROUNDING` and
`COMPLIANCE` hold the shared rules; `BASE_SYSTEM_PROMPT` and
`agent/chat.py::_STYLE` each interpolate them and add what is specific to their
path — tool-citation discipline (`[Source: <tool>]`) for the deep dive, DATA
block wording for the chat. Previously these were two independent texts and only
the chat one was hardened, so the deep dive was still missing the rules written
after live fabrication incidents.

**Free-tier models disregard negative instructions.** Observed while testing the
screen intent: given a table with the P/E column removed and an explicit "do not
supply a value", the models still emitted recalled-from-training P/Es. The fix
was structural, not textual — screen tables are now rendered from SQL and shown
to the user directly, with the model writing only the commentary. Treat prompt
instructions as guidance, not as a guarantee, on this tier of model. This is the
main reason the grounding rules cite specific observed failures rather than
stating the principle abstractly.

---

## 6. Non-LLM keys, for completeness

| Key | Used by | Purpose |
|---|---|---|
| `SERPAPI_KEY` | `services/search.py` | web search, 250/mo free |
| `SEARXNG_URL` | `services/search.py` | self-hosted fallback when SerpAPI is exhausted |
| `JINA_API_KEY` | `services/search.py` | URL content extraction |
| `FINNHUB_API_KEY` | `services/finnhub_news.py` | company news |
| `UPSTOX_ANALYTICS_TOKEN` | `services/upstox.py`, `upstox_stream.py` | market data + tick stream, 1yr validity |
| `UPSTOX_ACCESS_TOKEN` | `services/upstox.py` | holdings/portfolio only, expires daily ~03:30 IST |
| `UPSTOX_CLIENT_ID` / `_SECRET` / `_REDIRECT_URI` | `services/upstox_auth.py` | OAuth token exchange |

The two Upstox tokens are separate credentials that fail independently; Data
Health reports them separately for that reason.
