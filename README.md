# ARTHA Terminal

**A self-hosted research terminal for Indian equities and derivatives.** Live
NSE/BSE market data, an option-chain and F&O level engine, and an AI analyst that
is grounded in your own database rather than in the model's memory.

Read-only by design — order APIs are never wired — and built so every number on
screen can be traced to where it came from.

| | |
|---|---|
| **Web UI** | Next.js 15 · 16 pages · http://localhost:3000 |
| **API** | Starlette JSON + WebSocket · http://localhost:8000 |
| **Store** | SQLite (one file, in a Docker volume) |
| **Runs on** | Docker Compose · two containers |

📖 **[Architecture &amp; full reference →](docs/ARCHITECTURE.md)** · [Web UI notes](web/README.md) · [Every LLM call, documented](docs/PROMPTS.md)

---

## What you need

**To run it (the normal path):**

- **Docker Desktop** (or Docker Engine + Compose v2) — everything runs in two containers
- **~3 GB disk** for the images, plus whatever the database grows to (~200 MB after a full ingest)
- **An Upstox account** for live data — free to create, and the data APIs are free

**Only if you want to develop on it:** Python 3.12+ and Node 20+.

No local Python, Node, or SQLite install is needed just to run the terminal.

---

## Quick start

```bash
git clone https://github.com/personalaiengines/artha-terminal.git
cd artha-terminal

cp .env.example .env      # then fill in your keys — see below
docker compose up -d      # first run builds both images (~5 min)
```

Then open **http://localhost:3000**.

First boot creates the database schema and starts the scheduler, but the tables
are empty until you load data:

```bash
docker compose exec api python scripts/ingest_all.py     # ~10 min for the full universe
```

Check it came up:

```bash
curl http://localhost:8000/api/health
docker compose exec api python scripts/db_status.py      # row counts per table
```

> **Open the terminal on the machine running Docker.** No API route is
> authenticated and `/api/holdings` returns your real brokerage book, so the API
> binds to `127.0.0.1` only. Exposing it to a LAN needs real auth added first.

---

## API keys

Copy `.env.example` to `.env` and fill in what you need. **The app starts with an
empty `.env`** — it just degrades, and every screen tells you what it fell back
to rather than hiding it.

### Market data — start here

| Key | Needed for | Without it |
|---|---|---|
| `UPSTOX_ANALYTICS_TOKEN` | Live quotes, index levels, option chains, the tick stream | Falls back to Yahoo Finance, ~15 min delayed, no live ticks |
| `UPSTOX_CLIENT_ID`&nbsp;/&nbsp;`UPSTOX_CLIENT_SECRET` | The OAuth flow that issues the daily token | Portfolio pages stay empty |
| `UPSTOX_ACCESS_TOKEN` | Holdings, positions, P&L | Portfolio pages stay empty; market data is unaffected |
| `UPSTOX_REDIRECT_URI` | Must match your Upstox app exactly | OAuth callback fails |

Get these at **[developer.upstox.com](https://developer.upstox.com)** → create an
app. The two tokens are **different credentials with different lifetimes**: the
analytics token lasts a year and drives market data; the access token expires
daily around 03:30 IST and drives only the portfolio. They fail independently,
and Data Health reports them separately for exactly that reason. Re-authorize the
daily one in-app from Settings → Upstox.

Set `UPSTOX_REDIRECT_URI=http://localhost:3000/upstox/callback` and register the
same URI in your Upstox app — the callback page exchanges the code automatically.

### AI analyst — any one of these is enough

The model router walks these in order and falls through on rate limits, so one
free key gets you a working analyst. All have free tiers.

| Key | Where | Notes |
|---|---|---|
| `OPENROUTER_API_KEY` | [openrouter.ai](https://openrouter.ai/keys) | Default primary. Use `:free` model slugs |
| `NVIDIA_API_KEY` | [build.nvidia.com](https://build.nvidia.com) | Free NIM tier |
| `SAMBANOVA_API_KEY` | [cloud.sambanova.ai](https://cloud.sambanova.ai) | Fast, small context — used first for quick tasks |
| `GITHUB_MODELS_TOKEN` | [GitHub fine-grained PAT](https://github.com/settings/personal-access-tokens) with `models: read` | 128K context — used first for deep reports |
| `GROQ_API_KEY` / `GOOGLE_API_KEY` | [console.groq.com](https://console.groq.com) · [aistudio.google.com](https://aistudio.google.com) | Additional free tiers |
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) | **Paid**, opt-in. Leave blank to stay on the free stack |

Without any of them the terminal works fine — the AI Analyst page says the tiers
are exhausted instead of failing silently.

### News and search — optional

| Key | Needed for | Without it |
|---|---|---|
| `FINNHUB_API_KEY` | Company news ([finnhub.io](https://finnhub.io), instant free key) | News panels thin out |
| `SERPAPI_KEY` | Web search for the analyst (250 free/month) | Falls back to SearxNG |
| `SEARXNG_URL` | Self-hosted unlimited search fallback | Run one with `docker compose --profile search up -d` |
| `JINA_API_KEY` | Cleaner article extraction | Uses the raw page |

### Everything else

`ARTHA_DB_PATH` and `LOG_LEVEL` are the only other settings worth touching;
compose sets the database path for you.

---

## Everyday commands

```bash
docker compose logs -f api      # tail the API
docker compose down             # stop (your data survives)
docker compose down -v          # stop and DELETE the database volume

make up / down / logs / test / ingest / db-status / shell
```

**After changing code, rebuild** — source is baked into the images, so
`docker compose up -d` alone will not pick up an edit:

```bash
docker compose build api && docker compose up -d api     # Python change
docker compose build web && docker compose up -d web     # web/ change
```

---

## Tests

```bash
make test                                  # in the container
pytest tests/ -q                           # on the host, needs the dev venv
```

263 tests across 38 files. Tests that need real ingested data skip themselves on
a fresh checkout rather than failing.

---

## What's inside

- **Live data three ways** — WebSocket ticks, REST polling, and a last-known-good
  layer that serves the last confirmed value with a visible staleness badge
  rather than a blank panel or an invented number.
- **F&O level engine** — option-derived levels (max pain, OI walls, expected move)
  and price structure (pivots, CPR, Camarilla, prior day and week) merged into
  confluence zones and scored, with the reasoning spelled out per zone.
- **A charting page you can drive from the keyboard** — drawing tools,
  indicators, and a read cursor that announces each bar to a screen reader.
- **A grounded AI analyst** — routes intent, pulls facts from SQLite, and is
  forbidden from producing a number that is not in the data block.
- **Deterministic engines** — red flags and the 0-10 scorecard are computed in
  Python; the model presents them and cannot recompute or soften them.

The [architecture doc](docs/ARCHITECTURE.md) covers each of these properly.

---

## Research only

Educational and research software, not investment advice. The broker integration
is read-only, signals are soft (HOLD / WATCH / REVIEW — never buy or sell), and
the Analysis Score is not a recommendation. Consult a SEBI-registered investment
adviser before making investment decisions.

## License

MIT
