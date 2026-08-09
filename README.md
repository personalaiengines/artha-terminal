# ARTHA Terminal

**A self-hosted research terminal for the Indian markets.** Live NSE and BSE data,
an F&O option-chain and level engine, portfolio tracking, and an AI analyst that
answers from your own database rather than from a language model's memory.

[![CI](https://github.com/personalaiengines/artha-terminal/actions/workflows/ci.yml/badge.svg)](https://github.com/personalaiengines/artha-terminal/actions/workflows/ci.yml)
![Python 3.12](https://img.shields.io/badge/python-3.12-blue)
![Next.js 15](https://img.shields.io/badge/next.js-15-black)
![License MIT](https://img.shields.io/badge/license-MIT-green)

---

## Why this exists

Most market dashboards fail in one of two ways. They either hide where a number
came from, or they let a language model invent one.

ARTHA is built around a single rule: **every figure on screen must be traceable
to its source, and the model is never allowed to produce one.** The AI reads
data it was given and explains it. It cannot recall a price from training, round
a gap into an estimate, or attribute a figure to a broker it never consulted.
Where a value is missing, the interface says so — a stated gap is more useful
than a confident invention.

Three consequences follow from that rule, and they shape the whole codebase:

**Deterministic engines decide; the model only narrates.** The red-flag scanner
and the 0–10 scorecard are plain Python. Their output is auditable and
reproducible, and the model presents it verbatim — it cannot recompute, override,
or soften a finding.

**Degradation is visible, never silent.** When a feed fails, the terminal serves
the last confirmed value behind a staleness badge rather than a blank panel or a
plausible-looking guess. Every screen reports what it fell back to.

**Read-only by design.** Order-placement APIs are never wired. The broker
integration can read your book; it cannot trade it.

| | |
|---|---|
| **Web UI** | Next.js 15 · 17 pages · http://localhost:3000 |
| **API** | Starlette JSON + WebSocket · 41 routes · http://localhost:8000 |
| **Store** | SQLite — one file, in a Docker volume |
| **Runs on** | Docker Compose · two containers |
| **Tests** | 311 across 42 files |

📖 **[Architecture &amp; full reference →](docs/ARCHITECTURE.md)** · [Web UI notes](web/README.md) · [Every LLM call, documented](docs/PROMPTS.md)

---

## What's inside

**Live data, three ways.** WebSocket ticks for the fast path, REST polling as
fallback, and a last-known-good layer that keeps a stale-but-labelled value on
screen instead of an empty one.

**An F&O level engine.** Option-derived levels — max pain, OI walls, expected
move — merged with price structure — pivots, CPR, Camarilla, prior day and week
— into scored confluence zones, with the reasoning shown per zone rather than
hidden behind a number.

**A grounded AI analyst.** Routes intent, pulls facts from SQLite, and cites the
tool behind every claim. Runs on a tiered router across six free LLM providers
with automatic failover and rate-limit cooldowns, so one free key is enough.

**A keyboard-driven charting page.** Drawing tools, indicators, and a read cursor
that announces each bar to a screen reader.

**Deterministic risk engines.** Red flags and the scorecard, computed in Python,
presented by the model, never altered by it.

---

## Requirements

**To run it:**

- **Docker Desktop**, or Docker Engine with Compose v2 — everything runs in two containers
- **~3 GB disk** for images, plus database growth (~200 MB after a full ingest)
- **An Upstox account** — free to create, and the data APIs are free

**To develop on it:** Python 3.12+ and Node 20+.

Running the terminal needs no local Python, Node, or SQLite install.

---

## Quick start

```bash
git clone https://github.com/personalaiengines/artha-terminal.git
cd artha-terminal

cp .env.example .env      # fill in your keys — see below
docker compose up -d      # first run builds both images, ~5 min
```

Open **http://localhost:3000**.

First boot creates the schema and starts the scheduler, but the tables stay empty
until you load data:

```bash
docker compose exec api python scripts/ingest_all.py     # ~10 min for the full universe
```

Verify it came up:

```bash
curl http://localhost:8000/api/health
docker compose exec api python scripts/db_status.py      # row counts per table
```

> **Run the terminal on the machine hosting Docker.** No API route is
> authenticated and `/api/holdings` returns your real brokerage book, so the API
> binds to `127.0.0.1` only. Exposing it to a network requires adding real
> authentication first.

---

## Configuration

Copy `.env.example` to `.env` and fill in what you need. **The app starts with an
empty `.env`** — it degrades rather than failing, and every screen reports what it
fell back to.

### Market data — start here

| Key | Needed for | Without it |
|---|---|---|
| `UPSTOX_ANALYTICS_TOKEN` | Live quotes, index levels, option chains, tick stream | Falls back to Yahoo Finance, ~15 min delayed, no live ticks |
| `UPSTOX_CLIENT_ID`&nbsp;/&nbsp;`UPSTOX_CLIENT_SECRET` | The OAuth flow issuing the daily token | Portfolio pages stay empty |
| `UPSTOX_ACCESS_TOKEN` | Holdings, positions, P&L | Portfolio pages stay empty; market data unaffected |
| `UPSTOX_REDIRECT_URI` | Must match your Upstox app exactly | OAuth callback fails |

Create an app at **[developer.upstox.com](https://developer.upstox.com)**.

The two tokens are **different credentials with different lifetimes.** The
analytics token lasts a year and drives market data. The access token expires
daily around 03:30 IST and drives only the portfolio. They fail independently,
which is why Data Health reports them separately. Re-authorize the daily one from
Settings → Upstox.

Set `UPSTOX_REDIRECT_URI=http://localhost:3000/upstox/callback` and register the
same URI in your Upstox app — the callback page exchanges the code automatically.

### AI analyst — any one key is enough

The router walks these in order and falls through on rate limits. All have free
tiers.

| Key | Where | Notes |
|---|---|---|
| `GROQ_API_KEY` | [console.groq.com](https://console.groq.com) | Fastest tier, 131K context — leads both chains |
| `GOOGLE_API_KEY` | [aistudio.google.com](https://aistudio.google.com) | Independent quota pool |
| `OPENROUTER_API_KEY` | [openrouter.ai](https://openrouter.ai/keys) | Use `:free` model slugs |
| `NVIDIA_API_KEY` | [build.nvidia.com](https://build.nvidia.com) | Free NIM tier |
| `SAMBANOVA_API_KEY` | [cloud.sambanova.ai](https://cloud.sambanova.ai) | Fast, small context |
| `GITHUB_MODELS_TOKEN` | [Fine-grained PAT](https://github.com/settings/personal-access-tokens) with `models: read` | 128K context |
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) | **Paid**, opt-in. Leave blank to stay free |

Without any key the terminal still runs — the analyst reports that all tiers are
exhausted instead of failing silently.

### News and search — optional

| Key | Needed for | Without it |
|---|---|---|
| `FINNHUB_API_KEY` | Company news ([finnhub.io](https://finnhub.io)) | News panels thin out |
| `SERPAPI_KEY` | Web search for the analyst (250 free/month) | Falls back to SearxNG |
| `SEARXNG_URL` | Self-hosted unlimited search | Run one with `docker compose --profile search up -d` |
| `JINA_API_KEY` | Cleaner article extraction | Uses the raw page |

`ARTHA_DB_PATH` and `LOG_LEVEL` are the only other settings worth touching, and
Compose sets the database path for you.

---

## Everyday commands

```bash
docker compose logs -f api      # tail the API
docker compose down             # stop; your data survives
docker compose down -v          # stop and DELETE the database volume

make up / down / logs / test / ingest / db-status / shell
```

**Source is baked into the images, so rebuild after any code change** —
`docker compose up -d` alone will not pick up an edit:

```bash
docker compose build api && docker compose up -d api     # Python change
docker compose build web && docker compose up -d web     # web/ change
```

---

## Tests

```bash
make test                    # in the container — the authoritative run
pytest tests/ -q             # on the host, needs the dev venv
```

311 tests across 42 files. `make test` mounts the suite into a throwaway
container, because the production image deliberately ships no `tests/` directory.

Tests requiring real ingested data skip themselves on a fresh checkout rather
than failing.

---

## Research only

Educational and research software, not investment advice. The broker integration
is read-only, signals are soft — HOLD, WATCH, REVIEW, never buy or sell — and the
Analysis Score is not a recommendation. Consult a SEBI-registered investment
adviser before making investment decisions.

## License

MIT
