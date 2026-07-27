# F&O Chart Drawing — design + build log

**Status:** BUILT (native chart + TradingView bridge both shipped).
First captured 2026-07-24 as an idea; built out 2026-07-24 → 2026-07-25.

Goal: see the F&O support/resistance / max-pain / OI-wall / pivot levels on a live
price chart, without paying for or fighting TradingView.

---

## What exists now (two independent paths)

### Path 1 — Native ARTHA chart  ⭐ (the default, recommended)
An interactive candlestick chart on the F&O Analysis page with the key levels
overlaid as labelled horizontal price lines. Free, no CDP, no TradingView, runs
in Docker. This is Option A from the original idea.

Files:
- `services/upstox.py` — `get_intraday_candles(key, interval)` (today's live bars;
  the plain `get_candles` historical endpoint doesn't return the forming session).
- `services/fno_service.py`
  - `get_index_intraday(index, interval)` — today's live candles.
  - `get_index_history(index, interval, days)` — historical candles, **paged** in
    cap-sized windows (`_HIST_WINDOW`: 1minute=25d, 30minute=150d/request) and
    stitched, so fine intervals can still span ~1 year.
- `ui/components/charts.py` — `lightweight_candles_html(df, levels, kind_color, …)`
  builds a self-contained TradingView **lightweight-charts** page (crosshair, pan,
  zoom, kinetic scroll, `createPriceLine` per level).
- `ui/vendor/lightweight-charts.js` — the v4.2.0 standalone lib, **vendored and
  inlined** into the page (no CDN fetch → smooth, offline-safe). Ships via
  `COPY ui/` in the Dockerfile.
- `pages/4_FnO_Analysis.py` — the "📈 Live Price + Key Levels" section:
  - `_TF_CFG` — timeframe → (base interval, lookback days, resample rule).
  - `_hist` (30-min cache) + `_intra` (15s cache) + `_series_df` (merge history +
    today's live, dedupe by timestamp, sort, resample).
  - Controls: **Timeframe** select, **Show levels** multiselect (per-kind toggle),
    **🔴 Live refresh** checkbox.
  - `st.fragment(run_every=15)` auto-refresh, only for intraday bases during
    IST market hours.

Timeframes (`_TF_CFG`):
| tf | base | lookback | resample |
|----|------|----------|----------|
| 1m | 1minute | 10d | — |
| 5m | 1minute | 20d | 5min |
| 15m | 1minute | 365d (paged) | 15min |
| 30m | 30minute | 400d (paged) | — |
| 1D | day | 420d | — |
| 1W | week | 1200d | — |
| 1M | month | 2500d | — |

Behaviour notes:
- Times pushed as IST wall-clock (lib renders UTC, so +5:30 offset applied).
- Level lines coloured by kind via `_KIND_COLOR` (matches the TV bridge palette).
- Live refresh rebuilds the iframe (resets pan/zoom) — that's why it's a toggle;
  off = inspect freely.

### Path 2 — TradingView Desktop bridge (kept, optional)
Draws the same levels on the real TradingView app via Chrome DevTools Protocol.
Genuinely tick-live (rides TV's own feed). Its cost: paid/limited TV, an
interactive logon session, and CDP fragility.

Files:
- `services/tradingview_bridge.py` — `draw_levels` (refresh = remove our previous
  lines, draw new, remember IDs), `ensure_running`, `clear_artha_lines`, and
  **`unfreeze()`** (below).
- `scripts/draw_now.py` — on-demand one-shot draw.
- `scripts/draw_live.py` — **live loop**: redraws option-derived levels every
  `ARTHA_DRAW_INTERVAL`s (default 60, floor 15) during IST 09:15–15:30, exits after
  close (`session_over`) so one bounded run/day.
- `scripts/fno_daily.py` — daily one-shot for Task Scheduler.
- `scripts/install_live_task.ps1` — registers the live loop as a Windows Scheduled
  Task (daily, pre-IST-open, interactive session, `-Uninstall` to remove).

---

## The TradingView "chart froze" bug + fix
Symptom: after drawing levels, the live TV chart stopped moving.
Root cause: the CDP `tv` tool can leave the page's V8 **Debugger paused** — halts
the JS loop (no requestAnimationFrame, no tick rendering) even though the websocket
still receives data.
Fix: `tradingview_bridge.unfreeze()` — opens a fresh CDP session per page target on
:9222 and sends `Debugger.enable` + `Debugger.resume`. Auto-called at the end of
every live `draw_levels`. Manual unstick: close/relaunch TV, or F12→resume.

---

## Upstox drawing (Option B) — investigated, NOT built
Drawing on the actual pro.upstox.com order chart would mean driving its **embedded
TradingView charting-library widget** via CDP. Feasibility hinges on one unknown:
is the widget reachable from JS, or closured/iframed away?

- `scripts/upstox_probe.py` — read-only CDP probe. Launch Chrome with
  `--remote-debugging-port=9222`, log into pro.upstox.com, run it. Reports per
  frame whether a `createShape`-capable widget is exposed, then a verdict.
- Verdict path: reachable → thin bridge (mirror `tradingview_bridge`, call
  `activeChart().createShape`). Not reachable → synthetic-input drawing (brittle) or
  skip. **Not run yet.** Native chart (Path 1) already covers the R/S need, so
  Option B is low priority.

---

## Library review (why lightweight-charts)
- **lightweight-charts** (Apache-2.0, ~160KB, free, no license): candlesticks,
  real-time `series.update`, `series.createPriceLine` for R/S. No interactive
  drawing tools / studies — not needed (we compute levels server-side). ✅ chosen.
- **charting-library** (full/advanced): free but access-gated, needs a datafeed;
  its `createShape` API is what Upstox's embed would expose (Path 2 relevance only).
- Plotly (already installed): `add_hline` works but the candlestick feels clunky vs
  a real trading chart — replaced by lightweight-charts for the live view.

---

## Known ceilings / next steps
- Intraday history is capped by Upstox's 1-min window (~1 month/request). A year of
  15m is paged from 1-min (~15 requests, 30-min cached). Deeper/faster intraday
  history would need parallel paging or a coarser base for old bars.
- Live refresh rebuilds the chart (resets view). Smooth-live-without-reset needs a
  bidirectional Streamlit component (data pushed via `series.update`) — build only
  if the rebuild flicker becomes a real annoyance.
- No holiday gating on `draw_live` / caches yet; `UpstoxClient.get_market_holidays`
  exists if we want to skip trading holidays.
- Upstox real-time WS feed not integrated (candles are poll-based, per-minute).
