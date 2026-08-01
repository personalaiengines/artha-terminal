# ARTHA Terminal

**Real-time Indian equities research terminal.** Live NSE/BSE market data, a
grounded AI analyst, and deterministic risk engines — read-only, SEBI-safe.

Two containers:

| Service | Port | What it is |
|---|---|---|
| `artha-web` | 3000 | Next.js 15 UI — 16 pages, one design system ([`web/`](web/), see [web/README.md](web/README.md)) |
| `artha-api` | 8000 | Starlette JSON API + WebSocket over the Python services, engines and SQLite ([`api/`](api/)) |

The original Streamlit UI is retired to [`archive/streamlit-legacy/`](archive/streamlit-legacy/).
Nothing outside that folder runs Streamlit.

---

## Quick start

```bash
cp .env.example .env          # fill in your keys — see Configuration
docker compose up -d          # builds both images on first run

# web  http://localhost:3000
# api  http://localhost:8000/api/health
```

**Open the terminal on the Docker host.** No API route is authenticated —
`/api/holdings` returns the real brokerage book — so the API is published on
`127.0.0.1:8000` only. The web container still reaches it as `api:8000` over the
compose network, but a browser on another LAN device cannot: the tick
WebSocket is dialled straight from the page (`web/lib/use-ws.ts`), so such a
device loses live prices and silently falls back to REST polling. Widening this
means adding real authentication first.

First boot creates the SQLite schema in the `artha-db` volume and starts the
scheduler. To populate data:

```bash
docker compose exec api python scripts/ingest_all.py
```

### Everyday commands

```bash
docker compose logs -f api           # tail the API
docker compose logs -f web           # tail the UI
docker compose restart api           # config-only change
docker compose down                  # stop (data survives)
docker compose down -v               # stop and DELETE the database volume
```

### Rebuilding after a code change

Code is baked into the images, so a source edit needs a rebuild of the service
it touched:

```bash
docker compose build api && docker compose up -d api     # Python change
docker compose build web && docker compose up -d web     # web/ change
```

`docker compose up -d` alone will **not** pick up edited source.

### Make targets

```bash
make up / down / restart / logs
make test          # pytest inside the api container
make ingest        # scripts/ingest_all.py inside the api container
make db-status     # row counts for every table
make shell         # sh inside the api container
make clean         # down -v + remove images  (destroys the DB volume)
```

---

## Two databases — the most common confusion

| | Path | Used by |
|---|---|---|
| **Live** | `/data/db/artha.db` (Docker volume `artha-db`) | the `api` container — this is the real one |
| Dev copy | `db/artha.db` in the repo | anything you run on the host with the venv |

They drift apart immediately and hold different data. `.dockerignore` excludes
`*.db` and the named volume shadows `/app/db`, so **host-side ingestion never
reaches the container**. Check which is which:

```bash
docker compose exec api python scripts/db_status.py   # the live one
python scripts/db_status.py                           # the dev copy
```

It prints the file path first, so a surprising row count explains itself.
The live database currently holds 5,173 symbols, 735k daily candles, 3,016
fundamentals rows and 529 index members.

Running `uvicorn api.server:app` on the host starts a *second* API against the
dev copy. If it binds :8000 it shadows the container for `127.0.0.1` traffic and
you will be looking at stale data without noticing.

---

## Configuration

Copy `.env.example` to `.env`. Everything is optional except Upstox if you want
live quotes and holdings — the app degrades to Yahoo (~15 min delayed) without it.

```env
# LLM tiers — all free-tier; the router walks them in order (see AI section)
OPENROUTER_API_KEY=          # OpenRouter (Nemotron free models by default)
NVIDIA_API_KEY=              # Nvidia NIM
SAMBANOVA_API_KEY=           # SambaNova — fast, small context
GITHUB_MODELS_TOKEN=         # GitHub Models — 128K context
ANTHROPIC_API_KEY=           # optional direct Anthropic

# Search + news
SERPAPI_KEY=                 # 250 searches/mo free
SEARXNG_URL=                 # self-hosted fallback: docker compose --profile search up -d
JINA_API_KEY=                # URL content extraction
FINNHUB_API_KEY=             # company news

# Upstox (read-only — order APIs are never wired)
UPSTOX_ANALYTICS_TOKEN=      # market data + tick stream. 1 year validity
UPSTOX_ACCESS_TOKEN=         # portfolio/holdings only. Expires daily ~03:30 IST
UPSTOX_CLIENT_ID=
UPSTOX_CLIENT_SECRET=
UPSTOX_REDIRECT_URI=http://localhost:3000/upstox/callback
```

**The two Upstox tokens are different credentials and fail independently.** The
analytics token drives index levels and the live tick stream; the access token
drives holdings and P&L. Data Health reports them separately for exactly this
reason — an expired portfolio token does not mean market data is down. Re-authorize
the daily one from the banner or Settings → Upstox.

Also read: `ARTHA_DB_PATH` (set to `/data/db/artha.db` in compose),
`ARTHA_CORS_ORIGINS` (defaults to localhost:3000 / 127.0.0.1:3000).

---

## Project structure

```
artha-terminal/
├── api/
│   ├── server.py          # every REST route, SWR caching, lifespan, error handler
│   ├── udf.py             # UDF datafeed for the charts (OHLC only, no secrets)
│   └── ws.py              # /ws tick fan-out to browsers
│
├── agent/                 # AI analyst
│   ├── chat.py            # intent router + DB grounding (the analyst's brain)
│   ├── llm_client.py      # ModelRouter — free-tier fallback chain
│   ├── orchestration.py   # tool-use loop for deep dives
│   ├── tools.py           # tool registry
│   ├── debate.py          # bull/bear two-sided pass
│   ├── context_window.py  # summarising compressor for small-context tiers
│   └── prompts.py
│
├── engines/               # deterministic — the LLM presents, never re-derives
│   ├── red_flags.py       # rule-based risk detection
│   ├── scorecard.py       # weighted 0-10 analysis score
│   └── verification.py    # cross-source price consensus
│
├── ingestion/             # ETL, all scheduled by scheduler.py
│   ├── scheduler.py       # APScheduler, run tracking in ingestion_runs
│   ├── symbol_etl.py      # NSE/BSE symbol master
│   ├── price_etl.py       # daily OHLCV
│   ├── quotes.py          # intraday quote refresh (every 3 min in-session)
│   ├── index_members.py   # NSE index constituents (no hardcoded lists)
│   ├── index_history.py   # index OHLC
│   ├── fundamentals_etl.py
│   ├── compute_metrics.py # DMAs, returns, RSI, ATH/ATL
│   ├── compute_scores.py  # analysis_score
│   └── cache_cleanup.py
│
├── services/              # data sources and derived views
│   ├── upstox.py          # broker REST client
│   ├── upstox_stream.py   # market-data WebSocket (MarketDataStreamerV3)
│   ├── upstox_auth.py     # token exchange + status
│   ├── global_markets.py  # world board + India board + Gift Nifty
│   ├── constituents.py    # DB-backed index/sector membership
│   ├── breadth.py         # market pulse, sector rotation
│   ├── movers.py          # gainers/losers, sliced per index and sector
│   ├── data_health.py     # which feeds are live, and what is served if not
│   ├── last_good.py       # last-known-good persistence
│   ├── live_quotes.py, stock_data.py, instruments.py, freshness.py
│   ├── fno_service.py, fno_analysis.py, fno_narrative.py, fno_oi_read.py
│   ├── levels.py          # pivots, CPR, Camarilla, prior week — settled OHLC only
│   ├── intraday.py        # 1-minute bar store + resampler (5/15/60)
│   ├── institutional_flows.py, market_news.py, finnhub_news.py
│   ├── market_events.py, search.py, yahoo.py, stock_analysis_llm.py
│   └── tradingview_bridge.py   # optional TradingView Desktop CDP bridge
│
├── db/
│   ├── schema.sql         # symbol_master, prices_daily, fundamentals,
│   │                      # computed_metrics, index_members, last_good,
│   │                      # ingestion_runs, fii_dii_flows, shareholding,
│   │                      # agent_cache, search_cache, audit_log,
│   │                      # alerts, watchlists, watchlist_items
│   │                      # (the complete list — init_database() replays
│   │                      #  this file on every start, all IF NOT EXISTS)
│   └── __init__.py        # get_connection(), init_database(), migrations
│
├── web/                   # Next.js UI — see web/README.md
├── tests/                 # 38 files, run with pytest
├── scripts/               # ingest_all.py, backfills, ws_smoke.py, F&O draw scripts
└── archive/streamlit-legacy/   # the retired Streamlit app
```

---

## API surface

All under `http://localhost:8000`. Every response is `{"ok": bool, ...}`; a
failure is reported, never thrown at the client.

**Market** — `/api/health` · `/api/universe` · `/api/pulse` · `/api/movers` ·
`/api/indices` (Indian board + Gift Nifty) · `/api/global` (world indices +
commodities) · `/api/flows` · `/api/news` · `/api/events` · `/api/brief`

**Stock** — `/api/stock/{symbol}` · `/api/stock/{symbol}/analysis` · `/api/history`

**F&O** — `/api/fno/{index}` (game plan: spot, ATM, PCR, max pain, level zones) ·
`/api/fno/{index}/narrative` · `/api/fno/{index}/expiries` ·
`/api/fno/{index}/term` (ATM IV term structure) · `/api/fno/{index}/oi-read` ·
`/api/positions`

**Charts** — `/api/udf/config` · `/api/udf/symbols` · `/api/udf/search` ·
`/api/udf/history` · `/api/udf/time`. A UDF datafeed (the TradingView wire
contract) serving the 1-minute store, resampled to 5/15/60 server-side. The F&O
chart reads `/history` through a same-origin Next.js proxy; a range with no bars
answers `no_data`, never an interpolated candle.

**AI** — `/api/ai` (one-shot) · `/api/ai/stream` (SSE, used by the analyst page)

**Portfolio** — `/api/holdings` · `/api/portfolio/curve` · `/api/watchlists` ·
`/api/alerts`

**Ops** — `/api/data-health` · `/api/system/status` · `/api/ingestion/status` ·
`/api/ingestion/run` · `/api/upstox/status` · `/api/upstox/token` · `/api/ensure`

**WebSocket** — `/ws`. Subscribe with
`{"action":"subscribe","keys":["nifty50","RELIANCE"]}`; ticks come back as
`{"type":"tick","key":...,"symbol":...,"tick":{...}}`. Plain symbols and friendly
index names both resolve server-side — clients never handle Upstox's
pipe-delimited ISIN keys.

Responses are cached with stale-while-revalidate; TTLs are mirrored client-side
in [`web/lib/poll.ts`](web/lib/poll.ts) so polling never outpaces the cache.

---

## Scheduled jobs

`ingestion/scheduler.py`, all times IST. Every run is recorded in
`ingestion_runs` and surfaced on the Alerts page.

| Job | Schedule |
|---|---|
| `live_quotes` | every 3 min, 09:00–15:59, Mon–Fri |
| `market_news_curation` | every 10 min |
| `fno_game_plan` | 08:45, Mon–Fri |
| `price_etl` | 20:30 daily |
| `index_history` | 20:45 daily |
| `symbol_etl` | 21:00 Mon |
| `compute_metrics` | 22:00 daily |
| `compute_scores` | 22:30 daily |
| `index_members` | 20:15 Sun |
| `cache_cleanup` | 03:00 daily |

Trigger any of them by hand from Settings, or `POST /api/ingestion/run`.

---

## How live data works

Three layers, deliberately:

1. **WebSocket ticks** — `services/upstox_stream.py` holds the Upstox
   market-data socket and fans ticks out through `api/ws.py`. A full session
   moves ~370k ticks. Reconnects with backoff on its own.
2. **REST polling** — every page polls its endpoints on the TTLs in
   `web/lib/poll.ts`, so values stay current even if the socket is down.
   Polling deliberately does **not** pause when the market is closed.
3. **Last known good** — when an upstream fails, `services/last_good.py` serves
   the last values confirmed good, flagged with when they were good. A stale
   real number beats a blank or an invented one, but only if the staleness is
   visible — so it carries an "Out of date" badge on the panel and an entry on
   the Alerts page.

`services/data_health.py` answers "what is not live right now, since when, and
what is being served instead" for index membership, prices, both Upstox tokens,
the tick stream, stale feeds and failed ETLs.

---

## AI architecture

### Model routing

`ModelRouter` (`agent/llm_client.py`) walks a free-tier chain and falls through
on rate limits. `config.get_tier_chain()` orders it by task shape:

- **`quick`** (lookups, tags, curation): SambaNova → OpenRouter → Nvidia NIM
- **`deep`** (reports, long context): GitHub Models (128K) → OpenRouter → NIM → SambaNova

Defaults are Nemotron free models on OpenRouter and Llama 3.3 70B elsewhere;
all overridable in `.env`. If every tier is exhausted the UI says so plainly
rather than failing silently.

**[docs/PROMPTS.md](docs/PROMPTS.md)** documents every LLM call in the project —
the prompt, the model that answers it, and the key that pays for it — plus both
tier chains and how Anthropic's opt-in override differs across chat, streaming
and the tool loop.

### Intent routing

`agent/chat.py` resolves symbols by **word-boundary** match over tickers *and*
company names, longest-match-first — never substring, which used to make
"Summarise this week's news" resolve to MARIS and deep-dive a random microcap.
Then it routes:

| Intent | Trigger | Grounding |
|---|---|---|
| `lookup` | names a stock, asks one thing | factsheet from the DB |
| `deep` | "deep dive", "should I buy", "bull case" | factsheet + red flags + scorecard + peers + sector news |
| `compare` | 2+ symbols with "vs"/"compare" | factsheet for each |
| `portfolio` | "my portfolio", "my holdings" | live Upstox holdings + per-symbol facts |
| `screen` | "show me pharma stocks", "which banks are cheapest" | real NSE index constituents from `index_members` |
| `market` | anything else | live market snapshot + web search |

Follow-ups resolve against history, so "what about its debt?" keeps the subject.

### Grounding rules

The model is never asked to know the market from memory:

- Every number must come from the data block. No estimates, no recalled figures.
- Never invent intraday figures — the data carries a close with its date, not a
  day range or VWAP.
- Never attribute a number to a broker or vendor that isn't in the data.
- Deterministic engine output (red flags, scorecard) is presented verbatim; the
  LLM cannot override, soften or recompute it.
- Screen tables are rendered from SQL and shown to the user directly — the model
  writes only the commentary beneath them.
- Web search is off for `screen` intents, so a question about Indian pharma can't
  come back with Johnson & Johnson.

---

## Data sources

| Source | Used for |
|---|---|
| Upstox API v2 | index levels, live quotes, tick stream, holdings, option chains |
| NSE (nsearchives, live-analysis) | index constituents, top gainers/losers |
| Yahoo Finance (`yfinance`) | fallback quotes, world indices, commodities, fundamentals |
| Finnhub | company news |
| SerpAPI → SearxNG → Jina | web search and URL extraction |
| `exchange_calendars` | holiday-aware market status (XBOM for NSE/BSE) |

Index and sector membership is **always** ingested from NSE, never hardcoded.
A sector slice with no stored membership renders empty and says so.

---

## Development

```bash
python -m venv venv && venv/Scripts/activate     # Windows
pip install -r requirements.txt
cp .env.example .env

python -m db                                     # create the dev schema
python -m uvicorn api.server:app --port 8001     # NOT 8000 — see the two-DB note
cd web && npm install && npm run dev             # http://localhost:3000
```

### Tests

```bash
pytest tests/ -q                 # host, against the dev DB
make test                        # inside the container, against the live DB
```

38 test files, 262 tests. Tests that read the DB assert the *shape* of a result,
not specific values, because the two databases hold different data.

The web side has no test runner (adding one to assert a handful of pure
functions would cost more than the functions). The non-trivial browser logic
instead carries `assert`-based self-checks that compile and run with the `tsc`
already installed:

```bash
cd web
npx tsc lib/indicators.ts lib/indicators.check.ts lib/live-bar.ts lib/live-bar.check.ts         lib/chart-store.ts lib/chart-store.check.ts         --outDir .checkout --module commonjs --target es2022 --strict
node .checkout/indicators.check.js && node .checkout/live-bar.check.js && node .checkout/chart-store.check.js
```

---

## The F&O chart

The centre of the F&O page: price against the level map, on
[KLineChart](https://klinecharts.com) (Apache-2.0, on npm). It replaced a
lightweight-charts build for one reason — that library ships **no user drawing
tools**, so trendlines and Fibonacci had to be hand-coded onto it.

### What it draws, and where each number comes from

| Layer | Source |
|---|---|
| Daily bars | `/api/history` — the page's own fetch, 1Y by default |
| Intraday bars (1m/5m/15m/1h) | `/api/udf/history` — the 1-minute store, resampled server-side |
| Live movement | the shared Upstox tick socket, folded into the last bar |
| Level map | `/api/fno/{index}` — the same confluence zones the Level Map card lists |

Nothing here invents a bar. An empty response draws an empty chart with the
reason written beside it; a tick never opens a daily bar the store has not
published; streamed bars carry `volume: 0` because the tape streams no volume —
0 is the measurement, not a placeholder.

### Levels

Twelve level types, every one arithmetic on settled OHLC or the live option
chain — no forecast, no smoothing:

| From the option chain | From settled price |
|---|---|
| Call OI Wall, Put OI Wall | Classic pivots (P, R1/R2, S1/S2) |
| Max Pain | CPR (top / bottom) |
| Expected-move band (ATM straddle) | Camarilla H3 / L3 |
| | Prev Day High / Low / Close |
| | Prev Week High / Low |

Levels within 0.15% of each other **merge into one zone** — "Max Pain + CPR
Bottom + Pivot P + Prev Day Close" is one line four independent methods agree
on, which is what the 0-100 zone strength scores. Support and resistance are
re-derived from spot on every build, so a broken resistance becomes the next
support and is drawn `BROKEN` rather than quietly relabelled.

The picker (sliders button, or `S`) filters them: per line, or **Show all /
Hide all / Still holding / Close to price**. `L` hides the whole map.

### Reading it without a mouse

A canvas is invisible to a screen reader and unreachable by Tab, so the chart is
`role="application"`, focusable, and driven by the keyboard. `←`/`→` walk a read
cursor bar by bar; every stop draws a marker and announces one `aria-live`
sentence — shown on screen and read aloud:

> `7 Jul 11:45 IST · open 24,510.45 · high 24,528 · low 24,503.05 · close 24,524.6 · up 0.06% on the bar · nearest level Pivot R2 at 24,500.6, 0.10% below · bar 61 of 525`

The nearest level is in there deliberately: OHLC alone is not a reading of *this*
chart — price against the level map is what the page is for.

| Key | Does |
|---|---|
| `← →` | step the cursor one bar (`Shift`: ten) |
| `Home` / `End` | first / last bar |
| `+` / `−` | zoom |
| `R` | reset the view (or double-click the price axis) |
| `1`…`5` | 1m, 5m, 15m, 1h, 1D |
| `L` / `S` | hide the level map / pick lines |
| `I` / `?` | indicator guide / shortcut list |
| `F` / `Esc` | expand to the window / unwind |

### Indicators

MA, EMA, Bollinger, RSI, MACD, KDJ and Volume are KLineChart built-ins. **VWAP**
is registered from `web/lib/indicators.ts` rather than reimplemented, and **TWAP**
(time-weighted, volume-free) exists because the index intraday feed publishes no
volume at all — so VWAP is gated to daily bars and says why, instead of drawing a
line over zeros. On daily bars both anchor **once** across the loaded window; a
per-session anchor there would redraw each bar's own typical price.

`I` opens a guide with what each one measures, how it is read, and what it will
not tell you ("RSI can pin above 70 for weeks in a trend; it measures speed, not
direction"), plus plain-English definitions of every level type.

### Drawing tools

Horizontal line, trend line, ray, vertical, Fibonacci retracement and price
channel, with magnet snapping to OHLC values, undo, and clear-all. Drawings and
the whole toolbar setup **persist in `localStorage`**, drawings per index.
Anchors are timestamp + price only — never `dataIndex`, which is a position in
the current view — so a line drawn on 15m sits on the same prices on 1D.

---

## SEBI compliance

Research and education only.

- **Read-only broker integration.** Order APIs are never wired — architectural,
  not a toggle.
- The Analysis Score (0-10) is not a buy/sell recommendation.
- Soft signals only: HOLD / WATCH / REVIEW, never buy/sell/accumulate/exit.
- Every price field carries its provenance and freshness.
- No PII; the portfolio is session-scoped and the database is local.

Consult a SEBI-registered investment advisor before making investment decisions.

---

## Changelog

### 2026-08-01

The F&O chart rebuilt on KLineChart, and the level engine widened. Full
description under [The F&O chart](#the-fo-chart).

**New**

- **Charting moved to KLineChart** (Apache-2.0). The old lightweight-charts
  build had no drawing tools — the library ships none. Now: six drawing tools
  with magnet snapping, nine indicators, and confluence **zone bands** (a zone
  is a range; the previous library had no band primitive, so only its edges
  could be drawn).
- **Seven more levels for daily F&O** — CPR top/bottom, Camarilla H3/L3, prev
  day close, prev week high/low. All from the one yfinance fetch already made,
  all pure arithmetic on settled OHLC. NIFTY went from 8 zones to 10, with
  five methods now agreeing on the max-pain price.
- **Keyboard-operable, screen-reader-readable chart** — a read cursor that walks
  bars and announces each one, including the nearest level and the distance to
  it. Full shortcut set, expand-to-window, and a `?` sheet rendered from the same
  table the handler uses, so the two cannot drift.
- **Indicator guide and level glossary** in the page (`I`) — what each measures,
  how it is read, and what it does not tell you.
- **Drawings and chart setup persist** in `localStorage`, per index, anchored to
  timestamp + price.
- **UDF datafeed** (`api/udf.py`) serving the 1-minute store with 5/15/60
  resampled server-side; a range with no bars answers `no_data`, never a
  fabricated candle.

**Fixed**

- **The price axis was dead where the levels were.** Level tags were drawn with
  the library's `simpleTag`, whose y-axis figure consumes mouse events — with
  eight levels stacked around spot, the top ~40% of the axis could not be
  dragged or touched. Replaced with an event-transparent tag; `R` and a
  double-click now also reset a scale dragged into a corner.
- **A late tick could open a 22:00 candle on a closed market.** Ticks now carry
  the exchange's own `ltt` rather than the browser clock, and an intraday bar is
  never opened outside 09:15–15:30 IST. A settled bar stays settled.
- **VWAP on daily bars measured nothing** — it re-anchored every bar, making it
  that bar's own typical price. Anchored once across the window now, and the note
  under the chart says so.
- **A resolution switch fed the new series in one bar at a time** at the previous
  resolution's bar width: the empty payload shown while loading was claiming the
  cache key. Also, 22 daily bars used to render into the right quarter of an
  otherwise empty pane.
- **Axis tick text was under WCAG AA** (~3:1). Now ~8:1, with black-on-white
  crosshair labels.
- **`.env.bak.*` was neither tracked nor ignored** — a real backup full of live
  keys sat one `git add -A` away from being published. `.gitignore` now ignores
  every `.env` variant and un-ignores only `.env.example`. Nothing secret ever
  reached the history.

### 2026-07-29

Full trading-session monitoring run (272 samples, 06:41–15:44 IST) plus the
fixes it surfaced.

**Session results** — 16 endpoints at 100% availability across 4,352 checks;
p99 under 220 ms everywhere. Index levels moved on nearly every 2-minute sample
(Sensex 188 distinct values from 188 samples). 367,539 WebSocket ticks during
the session with zero silent windows. `live_quotes` fired 136 times with no
missed slots. Breadth tracked 24% → 80% intraday with no last-known-good
fallbacks needed.

**Fixed**

- **Job timestamps were 5.5 h wrong in the UI.** `ingestion_runs` wrote naive
  UTC while `next_run` carried `+05:30`; JS parses an offset-less ISO string as
  local time, so a job that had just finished showed as "7h ago" next to
  "Next: due now". Timestamps are now IST-aware, and legacy rows are labelled
  on read.
- **Data Health never cleared.** The prices check warned on 50 of 5,005 symbols
  — the delisted and suspended tail — in 272 of 272 samples. Now warns only
  above a 5% share, so the card means something when it lights up.
- **Gift Nifty showed two different prices.** It was fetched by both the India
  board (20 s cache) and the global board (300 s), so the topbar and the Markets
  page disagreed by up to 15 points. It now has one home: the India board.
- **Commodities never rendered.** The Markets page flattened indices and
  commodities into one list then took the first 8 — and the index list is
  exactly 8 long. Also fixed `status.state` normalization, which had made every
  open/closed flag `null`.
- **AI Analyst: list questions ignored the database.** "Show me pharma stocks"
  routed to `market` — a breadth snapshot plus a web search — and answered with
  Johnson & Johnson and AbbVie. Added the `screen` intent (above).
- **AI Analyst: ticker collisions.** "What's the dollar rupee rate?" resolved
  DOLLAR (Dollar Industries). 13 tickers that are also ordinary words now
  require case evidence in the question, so "OIL" still works but "oil prices"
  doesn't.
- **AI Analyst: two divergent prompts.** `/api/ai` had its own weaker system
  prompt and answered a price question with a close attributed to a "Kotak Neo
  intraday quote" and a fabricated day range. Both endpoints now share one
  hardened prompt.

### Earlier

- Market Breadth rebuilt: plain-English verdict, diverging advance/decline bar,
  log-spaced adv/dec scale so parity sits centre, sector participation strip.
- Sector Rotation made deterministic — it had reshuffled on every refresh
  because breadth alternated between a 50-stock and a 3,222-row universe.
- Index and sector membership de-hardcoded: `ingestion/index_members.py` pulls
  18 NSE constituent lists (529 members) weekly. `services/nifty50.py` deleted.
- Top movers sliced per index and sector.
- Last-known-good serving plus Data Health, so no panel ever goes blank silently.
- Live WebSocket ticks wired end to end; equity ticks had been dropped because
  they broadcast under ISIN keys while browsers subscribed by ticker.
- CORS restricted to configured origins; 29 duplicated try/except blocks in
  `api/server.py` replaced with one global handler.

---

## License

MIT

---

# Appendix · F&O chart drawing

Two independent paths to see support/resistance, max-pain, OI-wall and pivot
levels on a live chart.

**Path 1 — in the app (default).** [`web/components/widgets/kline-chart.tsx`](web/components/widgets/kline-chart.tsx),
built on [KLineChart](https://klinecharts.com) (Apache-2.0), documented in full
under **The F&O chart** below. Levels, drawing tools, indicators and live ticks
in the page itself — no external app, no licence to apply for.

**Path 2 — TradingView Desktop bridge (optional).** Draws the same levels on the
real TradingView app over the Chrome DevTools Protocol. Genuinely tick-live,
but needs a paid/limited TV, an interactive logon session, and tolerance for CDP
fragility.

- `services/tradingview_bridge.py` — `draw_levels`, `ensure_running`,
  `clear_artha_lines`, `unfreeze`
- `scripts/draw_now.py` — one-shot draw
- `scripts/draw_live.py` — redraws every `ARTHA_DRAW_INTERVAL` s (default 60,
  floor 15) during 09:15–15:30 IST, then exits
- `scripts/fno_daily.py`, `scripts/install_live_task.ps1` — Windows Task
  Scheduler wiring

*The frozen-chart bug:* drawing could leave the page's V8 debugger paused, which
halts the JS loop — the websocket keeps receiving but nothing renders.
`unfreeze()` opens a fresh CDP session and sends `Debugger.enable` +
`Debugger.resume`; it runs automatically after every live `draw_levels`.

**Known ceilings.** Intraday history is bounded by Upstox's 1-minute window.
Drawing on pro.upstox.com's embedded TradingView widget was investigated and not
built — `scripts/upstox_probe.py` is the read-only feasibility probe, never run;
Path 1 already covers the need.
