# ARTHA Terminal — Web UI

Ground-up redesign of the ARTHA Terminal front end as a premium, AI-native
institutional research workspace. Next.js 15 · React 19 · Tailwind v4 ·
Framer Motion · Recharts. One design system, 15 pages, every screen inherits it.

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
world board, **grounded AI Analyst** (`/api/ai`) and **AI Market Brief** (`/api/brief`).
Still geometry-only (no live feed): options-chain OI, F&O candlestick shape (drawn around
the real spot with real walls/max-pain overlaid).

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

- **No TanStack Table / React Query / Zustand.** Rows are static mock data, so a
  data-fetch and global-state layer has nothing to do yet. `components/ui/data-grid.tsx`
  is a hand-rolled sortable grid; `ui-store.tsx` is React context. Add the libraries
  when the backend wires up (server sort/filter, thousands of rows, live quotes).
- **Candlestick is custom SVG**, not a charting lib — full control of the dark
  aesthetic, crosshair, and level overlays in ~150 lines.

## Accessibility & sessions

WCAG-minded contrast, `:focus-visible` rings on every interactive element,
`prefers-reduced-motion` honored globally, keyboard-driven command palette (⌘K),
tabular numbers on all financial data, dark low-fatigue palette for long sessions.
