# Prompts, Models and Keys

Every LLM call this project makes: what the prompt is, which model answers it,
and which API key pays for it.

Verified end to end against the running containers on 2026-07-29 — every path
below was invoked and its answer checked for the failure modes the grounding
rules exist to prevent (see §7).

---

## 1. Providers and keys

Seven providers are wired. All are free-tier by design; the router falls through
on rate limits rather than failing.

| Provider | Endpoint | Key (`.env`) | Configured now |
|---|---|---|---|
| Groq | `api.groq.com/openai/v1/chat/completions` | `GROQ_API_KEY` | set |
| Google Gemini | `generativelanguage.googleapis.com/v1beta/openai/chat/completions` | `GOOGLE_API_KEY` | set |
| OpenRouter | `openrouter.ai/api/v1/chat/completions` | `OPENROUTER_API_KEY` | set |
| Nvidia NIM | `integrate.api.nvidia.com/v1/chat/completions` | `NVIDIA_API_KEY` | set |
| SambaNova | `api.sambanova.ai/v1/chat/completions` | `SAMBANOVA_API_KEY` | set |
| GitHub Models | `models.inference.ai.azure.com/chat/completions` | `GITHUB_MODELS_TOKEN` | set |
| Anthropic | `api.anthropic.com` | `ANTHROPIC_API_KEY` | empty — opt-in override, see §5 |

### Model names in force

Defaults live in `config.py`; `.env` overrides them. Current values:

| Setting | Value | Provider |
|---|---|---|
| `GROQ_MODEL` | `openai/gpt-oss-120b` (131K ctx) | Groq |
| `GOOGLE_MODEL` | `gemini-flash-latest` | Google Gemini |
| `OPENROUTER_PRIMARY_MODEL` | `nvidia/nemotron-3-ultra-550b-a55b:free` | OpenRouter |
| `OPENROUTER_FALLBACK_MODEL` | `nvidia/nemotron-3-super-120b-a12b:free` | OpenRouter |
| `NVIDIA_FALLBACK_MODEL` | `mistralai/mistral-nemotron` | Nvidia NIM |
| `NVIDIA_BACKUP_MODEL` | `deepseek-ai/deepseek-v4-pro` | Nvidia NIM |
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
1. Groq            openai/gpt-oss-120b                GROQ_API_KEY
2. Google Gemini   gemini-flash-latest                GOOGLE_API_KEY
3. SambaNova       Meta-Llama-3.3-70B-Instruct        SAMBANOVA_API_KEY
4. OpenRouter      nemotron-3-ultra-550b-a55b:free    OPENROUTER_API_KEY
5. OpenRouter      nemotron-3-super-120b-a12b:free    OPENROUTER_API_KEY
6. Nvidia NIM      mistralai/mistral-nemotron         NVIDIA_API_KEY
7. Nvidia NIM      deepseek-ai/deepseek-v4-pro        NVIDIA_API_KEY
```

**`task_shape="deep"`** — long context, multi-section output:

```
1. Groq            openai/gpt-oss-120b  (131K ctx)     GROQ_API_KEY
2. Google Gemini   gemini-flash-latest                 GOOGLE_API_KEY
3. GitHub Models   Llama-3.3-70B-Instruct  (128K ctx)  GITHUB_MODELS_TOKEN
4. OpenRouter      nemotron-3-ultra-550b-a55b:free     OPENROUTER_API_KEY
5. OpenRouter      nemotron-3-super-120b-a12b:free     OPENROUTER_API_KEY
6. Nvidia NIM      mistralai/mistral-nemotron          NVIDIA_API_KEY
7. Nvidia NIM      deepseek-ai/deepseek-v4-pro         NVIDIA_API_KEY
8. SambaNova       Meta-Llama-3.3-70B-Instruct         SAMBANOVA_API_KEY
```

Groq leads both chains and Google follows it: probed live 2026-07-30 they answer
in ~1.0-1.6s against 7-30s for the NIM rungs, both call tools correctly, and their
free quotas are independent of each other and of OpenRouter. Check any rung
yourself with `python scripts/ai_check.py models`, which prints
provider/model -> status, latency and tool support for every configured tier.

Three rungs were removed on 2026-07-30 because they were dead, not merely slow:
`meta/llama-3.1-405b-instruct` (HTTP 404, retired), `meta/llama-3.3-70b-instruct`
(no answer inside 70s) and `qwen/qwen3-next-80b-a3b-instruct` (HTTP 410 Gone,
which `.env.example` had been recommending). NIM latency is also unstable — the
same model measured 0.6s and then a 60s timeout minutes apart — so NIM sits at the
bottom of both chains and no rung should be ranked on a single measurement.

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

| Service | Endpoint | Prompt | Shape |
|---|---|---|---|
| `services/stock_analysis_llm.py` | `/api/stock/{sym}/analysis` | "rigorous, grounded equity analyst; never fabricate numbers, never give direct buy/sell advice" → 5-section stock read | `deep` |
| `services/fno_narrative.py` | `/api/fno/{index}/narrative` | `_SYSTEM` — "rigorous, grounded senior F&O/derivatives strategist for Indian index options" → 5-section option-chain read | `deep` |
| `services/market_news.py` | `/api/news` | "financial news editor for Indian markets; rank and summarise search results; never fabricate facts, headlines or URLs" | `quick` |
| `services/market_events.py` | `/api/events` | "extract scheduled economic events from search results; return ONLY a JSON array; never invent events or dates" | `quick` |
| `services/breadth.py` | **none — see below** | "senior Indian equity market strategist; exactly two sentences on today's internals" | `quick` |

`breadth.get_strategist_read()` has **no live caller**. It is exported and
reachable, but `/api/pulse` does not return it and nothing in `api/` or `web/`
requests it — the only import is
`archive/streamlit-legacy/ui/components/market_pulse.py`, from the retired UI.
It was rerouted through the router with the others for consistency; if the
Market Breadth card ever wants a written read, it is ready to wire. Left in
place rather than deleted because the archive still imports it.

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

**Free tiers fail transiently, and that is priced in.** Observed on 2026-07-29:
GitHub Models returned 429 on a deep call (cooled down 300s, OpenRouter served
it) and SambaNova failed once with an empty error, presumably a timeout, before
OpenRouter answered. Both were invisible to the caller — which is the point of
the chain. A blank `str(e)` does not match any cooldown pattern, so that tier is
retried on the next request rather than skipped; acceptable while such failures
stay isolated, worth revisiting if a provider starts timing out steadily.

**Free-tier models disregard negative instructions.** Observed while testing the
screen intent: given a table with the P/E column removed and an explicit "do not
supply a value", the models still emitted recalled-from-training P/Es. The fix
was structural, not textual — screen tables are now rendered from SQL and shown
to the user directly, with the model writing only the commentary. Treat prompt
instructions as guidance, not as a guarantee, on this tier of model. This is the
main reason the grounding rules cite specific observed failures rather than
stating the principle abstractly.

---

## 6. Measured cost of each path

Against the containers on 2026-07-29, warm (second call onward). The router's
tier chain is the variable — a tier that has to fall through adds its own
timeout before the next one answers.

| Path | Latency | Notes |
|---|---|---|
| `/api/ai/stream` first token | **1.0s** | what the analyst page feels like |
| `/api/ai` market | 1.2 – 1.9s | snapshot + web results |
| `/api/ai` lookup | 1.4 – 2.6s | one fact from the DB |
| `/api/ai` compare | 1.9 – 3.4s | two symbols side by side |
| `/api/ai` screen | 5.7 – 7.2s | SQL table + commentary |
| `/api/brief` | 4.6s cold, cached 15 min | 7-bullet round-up |
| `/api/stock/{sym}/analysis` | 6.8s cold, cached 1h | |
| `/api/fno/{index}/narrative` | 6.8s cold, cached 15 min | |
| `/api/news` | 12.4s cold, cached 15 min | 6 web searches, then ranking |
| `/api/events` | 24.6s cold, cached 1h | searches + extraction |
| `/api/ai` deep dive | **126.6s** cold, 0.5s repeat | 8 tools + 3 debate calls, `agent_cache` 6h |

The deep dive is the only genuinely slow path and it is inherent — eight tool
calls and a three-call bull/bear/judge debate. It is served over
`/api/ai/stream` in the UI, so the user watches each tool land rather than
waiting on a spinner.

Everything non-LLM stays far below this: all 20 API routes and all 6 web pages
measured p50 ≤ 47ms warm, max 62ms (`/api/universe`, 5,173 rows). No endpoint
exceeded 1s.

---

## 7. Verification

`scripts/ai_check.py` invokes every path above and greps each answer for the
fabrication patterns the grounding contract targets:

- a source attributed to a broker/terminal that was never consulted
  ("Kotak Neo", "Bloomberg terminal", …)
- "cannot access real-time data" / "as an AI language model" — the model
  disclaiming data it was actually handed
- "traded in a range of" — an invented intraday range

2026-07-29 run: all six AI paths and all four live service prompts clean, no
pattern matched. Automated equivalents live in
`tests/test_llm_routing_consistency.py` (139 tests pass).

---

## 8. Non-LLM keys, for completeness

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
