# ARTHA Terminal — Web UI

Ground-up redesign of the ARTHA Terminal front end as a premium, AI-native
institutional research workspace. Next.js 15 · React 19 · Tailwind v4 ·
Framer Motion · Recharts · KLineChart. One design system, 16 pages, every screen
inherits it.

## Run

```bash
cd web
npm install
npm run dev      # http://localhost:3000
npm run build    # production build (all routes prerender)
```

Fonts (Inter + Geist Mono) load from Google Fonts; offline, it falls back to the
system stack with no layout shift.

## Design system (one source of truth)

Everything visual is a token in [`app/globals.css`](app/globals.css) under
`@theme` — surfaces, intent colors, radius, elevation, motion. Change a token
there and the whole product moves together. Intent colors carry meaning and only
that meaning:

| Token | Meaning | Used for |
|-------|---------|----------|
| `up` (emerald) | positive performance | gains, bullish only |
| `down` (red) | negative performance | losses, bearish only |
| `ai` (purple) | AI | anything AI-generated only |
| `accent` (blue) | interaction | links, focus, actions only |
| `warn` (amber) | caution | risk flags, medium impact |

## Architecture

```
web/
├── app/                    # one file per route (thin — pages compose widgets)
│   ├── layout.tsx          # root + AppShell
│   ├── page.tsx            # Dashboard (executive workspace)
│   ├── markets/            # Market Overview
│   ├── portfolio/          # Portfolio Analytics
│   ├── watchlists/         # institutional data grid
│   ├── ai-analyst/         # ChatGPT/Perplexity-style, streaming + citations
│   ├── research/           # AI Research Workspace
│   ├── news/               # News Intelligence
│   ├── stocks/             # screener + /[symbol] signature research page
│   ├── options/  fno/      # derivatives (shared OptionChain)
│   ├── calendar/ alerts/ risk/ settings/
├── components/
│   ├── layout/             # Sidebar, Topbar, CommandPalette (⌘K), AppShell
│   ├── ui/                 # design-system primitives (Card, Button, Badge,
│   │                       #   Stat, DataGrid, Sparkline, CandleChart, charts)
│   └── widgets/            # composed, reused blocks (PageHeader, StockRow,
│                           #   NewsCard, OptionChain)
└── lib/                    # data.ts (mock), format.ts, portfolio.ts, nav.ts
```

**Rule enforced structurally:** pages never draw their own header, card, table,
or number style — they compose `components/ui` + `components/widgets`. Consistency
is not discipline, it's the only path available.

## Data — live, with mock fallback

Wired to the Python backend via a Starlette JSON API ([`../api/server.py`](../api/server.py)).
The flow: **client page → Next route handler ([`app/api/*`](app/api)) → Python API → services/DB**.

The seam is [`lib/use-api.ts`](lib/use-api.ts) — `useApi(path, mockFallback)` renders
the mock **instantly**, then swaps in live data when the API answers `ok`. A slow or
failed response is ignored, so **no page ever blanks or breaks** — worst case it shows
the deterministic mock ([`lib/data.ts`](lib/data.ts)).

Live now: equity universe (DB — real price/volume/RSI/52w/history), single-stock research,
market news (category-tagged), macro calendar, market breadth/sectors, FII/DII flows,
world board, **grounded AI Analyst** (`/api/ai`), **AI Market Brief** (`/api/brief`),
the full **option chain** (live OI/IV/greeks per strike) and the **F&O chart** — real
daily and intraday candles from `/api/history` and `/api/udf/history`, with live ticks
folded into the forming bar. Nothing on the F&O page is geometry any more.

**Null-safety:** the live API returns `null` for DB gaps (price, changePct, P/E…). All
formatters ([`lib/format.ts`](lib/format.ts)) and numeric UI primitives
([`components/ui/stat.tsx`](components/ui/stat.tsx)) are null-safe and render `—` — a bare
`toFixed`/`toLocaleString` on `null` previously threw and tripped the route error boundary
("Something went wrong on this view").

`ARTHA_API_URL` points at the API (`http://api:8000` in Docker, `http://localhost:8000` in dev).

`NEXT_PUBLIC_ARTHA_WS_URL` (browser-visible) points the live-tick WebSocket client
([`lib/use-ws.ts`](lib/use-ws.ts)) at the API's `/ws` endpoint. Defaults to
`ws://<current-hostname>:8000/ws` if unset, which covers plain `npm run dev` and any
host reachable on port 8000 without configuration. Note: `NEXT_PUBLIC_*` vars are inlined
at `next build` time — a Docker deployment on a different API host needs this passed as a
build arg, not just a container `environment:` entry.

## Deliberate scope cuts (v1)

- **No TanStack Table / React Query / Zustand.** `lib/use-api.ts` is ~60 lines of
  poll-and-swap and covers every page; `components/ui/data-grid.tsx` is a hand-rolled
  sortable grid; `ui-store.tsx` is React context. Add the libraries when the shape of
  the problem needs them (server-side sort/filter, tens of thousands of rows).
- **Two chart engines, on purpose.** `components/ui/candles.tsx` is a ~150-line custom
  SVG candlestick for the stock research page — full control of the dark aesthetic in
  less code than configuring a library. The F&O chart
  ([`components/widgets/kline-chart.tsx`](components/widgets/kline-chart.tsx)) is
  KLineChart, because that page needs drawing tools, an indicator set and tick-level
  streaming, and hand-rolling those is a project, not a component.
- **No test runner.** The non-trivial pure logic (`lib/indicators.ts`, `lib/live-bar.ts`,
  `lib/chart-store.ts`) carries `assert`-based self-checks run through the installed
  `tsc` — see the root README's Tests section. Add a runner when there is something
  to test that these cannot reach.

## Accessibility & sessions

WCAG-minded contrast, `:focus-visible` rings on every interactive element,
`prefers-reduced-motion` honored globally, keyboard-driven command palette (⌘K),
tabular numbers on all financial data, dark low-fatigue palette for long sessions.

The F&O chart is the hard case: a `<canvas>` is invisible to a screen reader and
unreachable by Tab. It is `role="application"` and focusable, with arrow keys
walking a read cursor bar by bar and announcing each stop through `aria-live` —
OHLC plus the nearest level and the distance to it. Full keyboard control of
resolution, zoom, level filtering and expansion; `?` lists the shortcuts.
