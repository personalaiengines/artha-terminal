"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { AlertTriangle, Maximize2, Minimize2, Plus } from "lucide-react";
import { PageHeader } from "@/components/widgets/page-header";
import { Button } from "@/components/ui/button";
import { Segmented, LiveDot } from "@/components/ui/primitives";
import { ChartPane, INDEX_KEY } from "@/components/widgets/chart-pane";
import {
  MAX_PANES, PRESETS, PRESET_ORDER, addPane, emptyLayout, movePane, readLayout,
  removePane, setPreset, setRes, setSymbol, writeLayout, type Layout, type Preset,
} from "@/lib/chart-grid";
import { usePaneData } from "@/lib/use-pane-data";
import { useLivePrices } from "@/lib/use-live-prices";
import { isStreaming } from "@/lib/live-bar";
import { cn } from "@/lib/utils";

// Split-screen charting: up to six panes over the three indices, each one the
// F&O chart in fill mode. Everything that can be decided without a DOM lives in
// lib/chart-grid (presets, the reducers, the restore parser); this file is the
// wiring — one layout in state, one data hook, one socket.
//
// Indices only, by binding decision: NIFTY, BANKNIFTY and SENSEX are the three
// instruments with both an intraday store and an option chain, so every pane can
// draw candles and a full level map. There is no symbol search here on purpose.

// A cold /api/fno call takes 10-20s and the route's own timeout is 20s, so a
// missing level map means nothing until that has elapsed. Announcing it earlier
// would accuse the chain of being down on every normal page load.
const CHAIN_GRACE_MS = 20_000;

export default function Charts() {
  // Deterministic on the server: one NIFTY pane. The saved layout is applied
  // AFTER the first render, never read into useState — the server renders this
  // markup too and localStorage on the client would make the two disagree. Same
  // rule the chart itself follows for its saved setup.
  const [layout, setLayout] = useState<Layout>(emptyLayout);
  const [restored, setRestored] = useState(false);
  // What the restore threw away, in words. A chart the user set up vanishing on
  // reload with nothing said about it is indistinguishable from a bug (R31).
  const [lost, setLost] = useState<string[]>([]);
  useEffect(() => {
    const r = readLayout();
    setLayout(r.layout); setLost(r.dropped); setRestored(true);
  }, []);
  // Gated on state, not a ref: both updates above land in one render, so the
  // first write carries the restored layout instead of overwriting it with the
  // defaults that were on screen for one paint.
  useEffect(() => { if (restored) writeLayout(layout); }, [restored, layout]);

  const { panes, preset } = layout;
  const symbols = panes.map((p) => p.symbol);
  const { candles, levels } = usePaneData(symbols);
  // One socket, one subscription per DISTINCT instrument — useLivePrices keys on
  // the deduplicated set, so NIFTY in three panes is one key (R22).
  const live = useLivePrices(symbols.map((s) => INDEX_KEY[s]));

  const [waited, setWaited] = useState(false);
  useEffect(() => {
    const id = setTimeout(() => setWaited(true), CHAIN_GRACE_MS);
    return () => clearTimeout(id);
  }, []);

  // Liveness is the age of the last tick, sampled — never "a tick arrived once".
  // useLivePrices keeps every entry it has ever set, so `some(live[key])` would
  // read LIVE all night, which is the exact latch R24 took out of the pane pill
  // while this header kept it. Same predicate, same 15s window.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 5_000);
    return () => clearInterval(id);
  }, []);

  const anyLevels = symbols.some((s) => levels[s]);
  const ticks = symbols.map((s) => live[INDEX_KEY[s].toUpperCase()]).filter(Boolean);
  const streaming = ticks.some((t) => isStreaming(t.at, now));
  // Three states, because "NO TICKS" after the close would be as much of a lie as
  // "LIVE" was: nothing yet, arriving, and arrived-then-stopped.
  const tapeLabel = streaming ? "LIVE" : ticks.length ? "TAPE QUIET" : "NO TICKS";
  const atMax = panes.length >= MAX_PANES;
  const maxWhy = `Six charts is the maximum — at 1440px a seventh pane is under 480px wide, where a candle stops being readable.`;

  // Full screen for the whole GRID, not for one pane — a pane already has its
  // own F/Esc expand, and this is the other thing a desk wants: six charts with
  // no sidebar, no topbar and no browser chrome in the way.
  //
  // Two mechanisms, because either alone is half the ask. The CSS layer (fixed
  // inset-0) is what removes the app's own chrome and is the part that always
  // works. The Fullscreen API on top of it is what removes the BROWSER's chrome,
  // and it can be refused — it needs a user gesture, iframes and some policies
  // block it, and Safari on iOS has never supported it on a div. So the request
  // is fire-and-forget: if it is denied the page is still full-window, which is
  // the useful 90%, rather than the button appearing to do nothing.
  const shellRef = useRef<HTMLDivElement>(null);
  const [full, setFull] = useState(false);

  // The browser is the source of truth for native fullscreen: Esc, F11 and the
  // OS window buttons all exit it without going through our handler. Sync from
  // its event rather than trusting our own flag to have stayed correct.
  useEffect(() => {
    const sync = () => { if (!document.fullscreenElement) setFull(false); };
    document.addEventListener("fullscreenchange", sync);
    return () => document.removeEventListener("fullscreenchange", sync);
  }, []);

  // Esc has to work even when the native request was refused — in that case the
  // browser has no fullscreen to exit, so nothing else would take the key. Bound
  // to the shell, not the window: a pane's own Esc (cancel a drawing, drop the
  // read cursor, collapse the pane) must resolve first, and a keydown that
  // reached the shell has already bubbled past the focused pane's handler.
  const onShellKey = (e: React.KeyboardEvent) => {
    if (e.key === "Escape" && full && !document.fullscreenElement) {
      e.preventDefault();
      setFull(false);
    }
  };

  const toggleFull = useCallback(() => {
    if (full) {
      setFull(false);
      if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
      return;
    }
    setFull(true);
    shellRef.current?.requestFullscreen?.().catch(() => {
      // Refused. The CSS layer above already ran, so the grid is full-window.
    });
  }, [full]);

  // Every mutation below goes through the functional updater, never
  // `setLayout(reducer(layout, …))`.
  //
  // `layout` in a handler is the value from the render that created the handler.
  // Two panes changed inside one React batch therefore both compute from the SAME
  // starting layout and the second write wins — five of six simultaneous symbol
  // assignments were lost, deterministically, when a runtime check clicked six
  // panes with no yield between them. One person clicking one pane at a time
  // never sees it, which is exactly what makes it worth removing rather than
  // relying on nobody hitting it.
  const changePreset = (p: Preset) => {
    // The confirm reads the layout on screen, which is the one the user is
    // looking at and deciding about. The WRITE still recomputes from the latest
    // state — a reducer passed to setLayout must be pure, and window.confirm is
    // not, so it cannot move inside the updater.
    const { dropped } = setPreset(layout, p);
    // Every pane holds an instrument here — there are no empty slots — so a
    // reduction always throws away a chart someone set up. One native confirm;
    // a modal component for a yes/no is not worth the code (R7).
    if (dropped.length && !window.confirm(
      `${dropped.length} chart${dropped.length > 1 ? "s" : ""} (${dropped.map((d) => d.symbol).join(", ")}) `
      + `will be removed from the layout. Continue?`
    )) return;
    setLayout((l) => setPreset(l, p).layout);
  };

  return (
    // The shell is what goes full screen, so everything the grid needs — the
    // preset control, Add chart, the exit button — has to live inside it. A
    // control left outside would simply vanish, and the way out with it.
    <div ref={shellRef} onKeyDown={onShellKey}
      className={cn(full && "fixed inset-0 z-50 flex flex-col overflow-auto bg-void p-3")}>
      {/* The page title is the first thing to go: in full screen the charts are
          the content, and a 96px header is a sixth of a laptop's height. */}
      {!full && (
        <PageHeader eyebrow="Trading" title="Charts · split screen"
          description="Up to six charts side by side over the three indices, each with its own resolution, indicators and drawings. The level map is the same one the F&O page draws."
          actions={<LiveDot label={tapeLabel} />} />
      )}

      {/* What the saved layout lost on the way back, and why. The layout is
          rewritten the moment it is restored, so the drop is already permanent —
          the least this page can do is name it once (R31). */}
      {lost.length > 0 && (
        <div className="mb-3 rounded-[var(--radius-sm)] border border-warn/30 bg-warn-soft/40 px-3 py-2">
          <div className="flex items-center gap-2">
            <AlertTriangle size={14} className="shrink-0 text-warn" />
            <span className="text-[12px] text-frost">
              {lost.length === 1 ? "One saved chart" : `${lost.length} saved charts`} could not be restored.
            </span>
            <button onClick={() => setLost([])}
              className="ml-auto rounded-[6px] px-2 py-0.5 text-[11px] text-muted hairline hover:text-frost">
              Dismiss
            </button>
          </div>
          <ul className="mt-1 list-disc pl-8 text-[11.5px] leading-snug text-mist">
            {lost.map((d) => <li key={d}>{d}</li>)}
          </ul>
        </div>
      )}

      {/* One banner for the page, never one per pane (R26). Every pane below
          keeps drawing its stored bars either way. */}
      {waited && !anyLevels && (
        <div className="mb-3 flex flex-wrap items-center gap-2 rounded-[var(--radius-sm)] border border-warn/30 bg-warn-soft/40 px-3 py-2">
          <AlertTriangle size={14} className="shrink-0 text-warn" />
          <span className="text-[12px] text-frost">
            No level map for {[...new Set(symbols)].join(", ")} — Upstox may be unauthenticated,
            outside market hours, or unreachable. The charts keep drawing their stored bars.
          </span>
        </div>
      )}

      <div className={cn("flex flex-wrap items-center gap-2", full ? "mb-2 shrink-0" : "mb-3")}>
        <Segmented value={preset} onChange={changePreset}
          options={PRESET_ORDER.map((p) => ({ label: p, value: p }))} size="sm" />
        <Button size="sm" onClick={() => setLayout(addPane)} disabled={atMax}
          title={atMax ? maxWhy : "Add another chart to the layout"}>
          <Plus size={14} /> Add chart
        </Button>
        <Button size="sm" variant="ghost" onClick={toggleFull}
          aria-pressed={full}
          title={full ? "Leave full screen (Esc)" : "Fill the screen with the grid — hides the sidebar and the browser chrome"}>
          {full ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
          {full ? "Exit full screen" : "Full screen"}
        </Button>
        {/* The tape indicator moves here in full screen — its home is the page
            header, which is hidden, and "is this live?" is not a question to
            leave unanswered on a screen showing six charts. */}
        {full && <LiveDot label={tapeLabel} />}
        {/* disabled:pointer-events-none swallows the button's own tooltip, so the
            reason is on screen as well as on the control. */}
        {atMax && !full && <span className="text-[11px] text-faint">{maxWhy}</span>}
        {!full && (
          <span className="text-[11px] text-faint xl:hidden">
            Below 1280px the grid stacks to one column — each chart keeps its own instrument and setup.
          </span>
        )}
      </div>

      {/* Rows are 1fr of a viewport-tall grid where the presets tile, and at
          least 320px each where they stack (R4). Keyed by pane.id and never by
          index: on a reorder or a removal React would otherwise hand the wrong
          chart instance to a pane and throw away its zoom, drawings and stream. */}
      {/* Full screen swaps the height source: the grid becomes the flex child
          that takes whatever the shell has left, instead of a viewport
          calculation that assumed a page header and a sidebar were above it.
          Below xl the presets stack to one column, so six 320px rows overflow —
          the shell scrolls rather than clipping the last chart. */}
      <div className={cn("grid min-h-0 gap-2 auto-rows-[minmax(320px,1fr)]",
        full ? "flex-1" : "xl:h-[calc(100vh-17rem)] xl:min-h-[680px]", PRESETS[preset].cls)}>
        {panes.map((pane, i) => (
          <ChartPane key={pane.id} pane={pane}
            tick={live[INDEX_KEY[pane.symbol].toUpperCase()]}
            candles={candles[pane.symbol] ?? []}
            plan={levels[pane.symbol] ?? null}
            canLeft={i > 0} canRight={i < panes.length - 1} canRemove={panes.length > 1}
            onSymbol={(s) => setLayout((l) => setSymbol(l, pane.id, s))}
            onRes={(r) => setLayout((l) => setRes(l, pane.id, r))}
            onMove={(dir) => setLayout((l) => movePane(l, pane.id, dir))}
            onRemove={() => setLayout((l) => removePane(l, pane.id))}
          />
        ))}
      </div>
    </div>
  );
}
