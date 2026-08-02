---
title: Self-hosted Indian stock market dashboard
description: >-
  Live NSE and BSE market data through the Upstox API, an F&O option chain and
  level engine, portfolio tracking, and an AI analyst grounded in your own
  database. Open source, MIT, runs in Docker.
---

# ARTHA Terminal

**A self-hosted dashboard for the Indian stock market.** Live NSE and BSE data
through the Upstox API, an F&O option chain and level engine, portfolio
tracking, and an AI analyst grounded in your own database rather than in the
model's memory.

Open source (MIT), runs on your own machine in two Docker containers, and
read-only by design — order APIs are never wired.

[View on GitHub](https://github.com/personalaiengines/artha-terminal){: .btn }
[Quick start](https://github.com/personalaiengines/artha-terminal#quick-start){: .btn }
[Architecture](ARCHITECTURE.html){: .btn }

---

## What it does

**Live market data, three ways.** A WebSocket tick stream from Upstox, REST
polling on top of it, and a last-known-good layer that serves the last confirmed
value with a visible staleness badge — rather than a blank panel or an invented
number. A full trading session moves about 370,000 ticks through it.

**An F&O level engine.** Option-derived levels (max pain, call and put OI walls,
the expected-move band from the ATM straddle) merged with price structure
(classic pivots, CPR, Camarilla, previous day and week) into confluence zones.
Levels within 0.15% of each other collapse into one zone and are scored 0–100,
with the reasoning written out: *"Max Pain + CPR Bottom + Pivot P + Prev Day
Close agree within 0.04%"*.

**A charting page you can drive from the keyboard.** Candles, six drawing tools,
nine indicators, and a read cursor that walks bars and announces each one — OHLC
plus the nearest level and the distance to it — so the chart is usable with a
screen reader, which a `<canvas>` normally is not.

**A grounded AI analyst.** It routes your question by intent, pulls the facts out
of SQLite, and is forbidden from producing a number that is not in the data
block. Screens are rendered from SQL; the model writes only the commentary.
Deterministic engines (red flags, the 0–10 scorecard) are computed in Python and
presented verbatim — the model cannot recompute or soften them.

**A stock screener and portfolio tracker.** The equity universe with real price,
volume, RSI, 52-week and history from the database; holdings and P&L from your
Upstox account when you connect it.

---

## What you need

- **Docker Desktop** (or Docker Engine with Compose v2)
- **~3 GB of disk** for the images
- **An Upstox account** for live data — free, and the market-data APIs are free

No local Python, Node or SQLite install is needed to run it.

```bash
git clone https://github.com/personalaiengines/artha-terminal.git
cd artha-terminal
cp .env.example .env      # add your keys
docker compose up -d
```

Then open `http://localhost:3000`. The
[README](https://github.com/personalaiengines/artha-terminal#readme) lists every
API key, what it unlocks, and what happens without it — the app starts with an
empty `.env` and degrades honestly rather than failing.

---

## Documentation

- **[Architecture](ARCHITECTURE.html)** — how live data flows, the API surface,
  scheduled jobs, the AI routing and grounding rules, the F&O chart in depth
- **[Every LLM call, documented](PROMPTS.html)** — each prompt, the model that
  answers it, and the key that pays for it
- **[Web UI notes](https://github.com/personalaiengines/artha-terminal/blob/master/web/README.md)**
  — the design system and the deliberate scope cuts

---

## Built with

Next.js 15 · React 19 · Tailwind v4 · KLineChart · Starlette · Python 3.12 ·
SQLite · APScheduler · Upstox API v2 · yfinance

---

*Research and educational software, not investment advice. The broker
integration is read-only, signals are soft (HOLD / WATCH / REVIEW — never buy or
sell), and the Analysis Score is not a recommendation. Consult a SEBI-registered
investment adviser before making investment decisions.*
