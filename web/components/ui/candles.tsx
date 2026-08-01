"use client";
import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";

type Candle = { t: string; open: number; high: number; low: number; close: number; volume: number };

/** A horizontal reference line. Everything past `color` is optional so existing
 *  callers that pass `{price,label,color}` keep working unchanged. */
export type Level = {
  price: number;
  label: string;
  color: string;
  /** `lo`/`hi` draw the level as a translucent BAND (a confluence zone spans a range). */
  lo?: number;
  hi?: number;
  kind?: string;
  /** price has traded through this level this session -> drawn broken, never relabelled */
  crossed?: boolean;
  /** 0-100; drives line weight so the strongest level is the thickest line */
  strength?: number;
  /** rule-derived justification, rendered verbatim in the tooltip */
  basis?: string;
  /** "INTACT" | "AT PRICE" | "BROKEN" — shown as-is when supplied */
  state?: string;
};

export type Timeframe = "1M" | "3M" | "6M" | "1Y";
/** Days to request per timeframe. Exported so the page and the chart agree on one mapping. */
export const TIMEFRAME_DAYS: Record<Timeframe, number> = { "1M": 22, "3M": 66, "6M": 132, "1Y": 250 };
const TIMEFRAMES: Timeframe[] = ["1M", "3M", "6M", "1Y"];

const MIN_BARS = 20;      // floor on how far the wheel/pinch can zoom in
const ZOOM_STEP = 1.15;   // per wheel notch
const HIT_PX = 6;         // pointer distance that counts as "on" a level line

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

// Custom SVG candlestick with crosshair + level lines. No charting lib — full
// control of the TradingView-style dark aesthetic, and it's ~150 lines.
// (recharts IS installed and used by chart.tsx; the candle chart stays hand-rolled
// on purpose — zoom/pan/level hit-testing here are cheaper than fighting a wrapper.)
export function CandleChart({
  data, height = 360, levels = [], spot, timeframe, onTimeframe,
}: {
  data: Candle[];
  height?: number;
  levels?: Level[];
  /** live price — always kept inside the visible range, and drawn as a solid line (R7) */
  spot?: number | null;
  timeframe?: Timeframe;
  /** supply this to render the 1M/3M/6M/1Y selector; the page owns the fetch */
  onTimeframe?: (tf: Timeframe) => void;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(900);
  const [hover, setHover] = useState<{ x: number; y: number; i: number } | null>(null);
  const [view, setView] = useState<{ i0: number; n: number } | null>(null);

  // Live geometry for the imperative wheel handler (registered once, reads this).
  const geo = useRef({ cw: 1, i0: 0, n: 0, len: 0, plotW: 1 });
  const drag = useRef<{ x: number; i0: number } | null>(null);
  const ptrs = useRef(new Map<number, number>());
  const pinch = useRef<{ dist: number; n: number; i0: number; frac: number } | null>(null);

  const ready = data.length > 0;

  // Timeframe change refetches a different series; start it fully zoomed out.
  useEffect(() => { setView(null); }, [timeframe]);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setW(e.contentRect.width));
    ro.observe(el);

    // React's onWheel is attached passively, so preventDefault() inside it is a
    // silent no-op and the PAGE scrolls while you try to zoom. Register it here.
    const onWheel = (e: WheelEvent) => {
      const g = geo.current;
      if (!ready || g.len < 2) return;   // empty state: nothing to zoom, don't eat the scroll
      e.preventDefault();
      const frac = clamp((e.clientX - el.getBoundingClientRect().left) / g.plotW, 0, 1);
      const next = g.n * (e.deltaY > 0 ? ZOOM_STEP : 1 / ZOOM_STEP);
      applyZoom(next, frac, g.i0 + frac * g.n);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => { ro.disconnect(); el.removeEventListener("wheel", onWheel); };
  }, [ready]);

  // Zoom to `nextN` visible bars while keeping `anchor` (a fractional data index)
  // under the same fraction of the plot width.
  const applyZoom = (nextN: number, frac: number, anchor: number) => {
    const len = geo.current.len;
    if (len < 2) return;
    const n = Math.round(clamp(nextN, Math.min(MIN_BARS, len), len));
    const i0 = Math.round(clamp(anchor - frac * n, 0, len - n));
    setView(n >= len ? null : { i0, n });
  };

  // No candles → don't compute an Infinity/NaN scale; show an honest empty state.
  if (!ready) {
    return (
      <div ref={wrap} className="flex w-full items-center justify-center text-[12.5px] text-muted" style={{ height }}>
        No price history available.
      </div>
    );
  }

  const padR = 56, padB = 24, padT = 8;
  const volH = 56;
  const chartH = height - padB - volH;
  const plotW = Math.max(1, w - padR);

  // Clamp the viewport against the current data instead of resetting it on every
  // poll — a refresh that adds a bar must not throw away the user's zoom.
  const n = view ? clamp(view.n, Math.min(MIN_BARS, data.length), data.length) : data.length;
  const i0 = view ? clamp(view.i0, 0, data.length - n) : 0;
  const vis = view ? data.slice(i0, i0 + n) : data;

  // R7: the extent always contains every level (and its band) and live spot, so a
  // level can never float off-canvas above the candles.
  const bounds: number[] = [];
  for (const d of vis) bounds.push(d.high, d.low);
  for (const l of levels) {
    bounds.push(l.price);
    if (l.lo != null) bounds.push(l.lo);
    if (l.hi != null) bounds.push(l.hi);
  }
  if (spot != null && Number.isFinite(spot)) bounds.push(spot);
  const rawMin = Math.min(...bounds), rawMax = Math.max(...bounds);
  const pad = ((rawMax - rawMin) || Math.abs(rawMax) * 0.01 || 1) * 0.015;
  const min = rawMin - pad, max = rawMax + pad;
  const range = max - min || 1;
  // Index volume is published late — today's bar can legitimately read 0. That is
  // not missing data: keep the candle, just draw no volume bar.
  const maxVol = Math.max(0, ...vis.map((d) => d.volume)) || 1;

  const y = (p: number) => padT + chartH - ((p - min) / range) * chartH;
  const cw = plotW / vis.length;
  const bw = Math.max(1.5, cw * 0.62);
  geo.current = { cw, i0, n, len: data.length, plotW };

  const active = hover ? vis[hover.i] : vis[vis.length - 1];
  const upC = "var(--color-up)", downC = "var(--color-down)";

  const hitLevel = hover ? levels.find((l) => Math.abs(y(l.price) - hover.y) <= HIT_PX) : undefined;
  const tickIdx = Array.from({ length: Math.min(5, vis.length) }, (_, k) =>
    Math.round((k * (vis.length - 1)) / Math.max(1, Math.min(5, vis.length) - 1)));

  const endPointer = (e: ReactPointerEvent<SVGSVGElement>) => {
    ptrs.current.delete(e.pointerId);
    drag.current = null;
    if (ptrs.current.size < 2) pinch.current = null;
    if (e.currentTarget.hasPointerCapture?.(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId);
  };

  return (
    <div ref={wrap} className="relative w-full select-none" style={{ height }}>
      {/* OHLC readout */}
      {active && (
        <div className="absolute left-3 top-2 z-10 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] tnum pointer-events-none">
          <span className="text-muted">{active.t}</span>
          <span className="text-muted">O <span className="text-frost">{active.open}</span></span>
          <span className="text-muted">H <span className="text-frost">{active.high}</span></span>
          <span className="text-muted">L <span className="text-frost">{active.low}</span></span>
          <span className="text-muted">C <span className={active.close >= active.open ? "text-up" : "text-down"}>{active.close}</span></span>
        </div>
      )}

      {/* Timeframe + zoom reset. Hand-rolled rather than <Segmented>: that primitive
          uses a shared framer-motion layoutId="seg", and both pages that mount this
          chart already render one, so a second would fight it for the highlight. */}
      {(onTimeframe || view) && (
        <div className="absolute right-2 top-2 z-10 flex items-center gap-1">
          {view && (
            <button onClick={() => setView(null)} title="Reset zoom"
              className="rounded-[7px] px-2 py-1 text-[11px] font-medium text-muted hover:text-frost hairline bg-void">
              {n}/{data.length} · reset
            </button>
          )}
          {onTimeframe && (
            <div className="inline-flex items-center gap-0.5 rounded-[var(--radius-sm)] bg-void p-0.5 hairline">
              {TIMEFRAMES.map((tf) => (
                <button key={tf} onClick={() => onTimeframe(tf)} aria-pressed={timeframe === tf}
                  className={`rounded-[7px] px-2.5 py-1 text-[11px] font-medium transition-colors ${
                    timeframe === tf ? "bg-raised text-frost hairline" : "text-muted hover:text-mist"}`}>
                  {tf}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Level tooltip — the basis string is the product; it renders verbatim. */}
      {hover && hitLevel && (
        <div className="pointer-events-none absolute z-20 max-w-[260px] rounded-[var(--radius-sm)] bg-void p-2.5 text-[11px] leading-snug hairline shadow-lg"
          style={{ left: clamp(hover.x + 14, 4, Math.max(4, w - 270)), top: clamp(y(hitLevel.price) + 10, 4, Math.max(4, height - 96)) }}>
          <div className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-full" style={{ background: hitLevel.color }} />
            <span className="font-semibold text-frost">{hitLevel.label}</span>
            <span className="tnum text-mist">{hitLevel.price.toFixed(hitLevel.price >= 1000 ? 0 : 2)}</span>
          </div>
          <div className="mt-1 flex flex-wrap gap-x-3 text-muted tnum">
            <span className={hitLevel.crossed ? "text-warn" : ""}>{hitLevel.state ?? (hitLevel.crossed ? "BROKEN" : "INTACT")}</span>
            {spot != null && spot !== 0 && (
              <span>{((hitLevel.price - spot) / spot * 100 >= 0 ? "+" : "")}{((hitLevel.price - spot) / spot * 100).toFixed(2)}% from spot</span>
            )}
            {hitLevel.strength != null && <span>strength {hitLevel.strength}/100</span>}
          </div>
          {hitLevel.basis && <div className="mt-1.5 text-mist">{hitLevel.basis}</div>}
        </div>
      )}

      <svg
        width={w} height={height}
        style={{ touchAction: "none" }}
        className={drag.current ? "cursor-grabbing" : "cursor-crosshair"}
        onPointerDown={(e) => {
          ptrs.current.set(e.pointerId, e.clientX);
          e.currentTarget.setPointerCapture(e.pointerId);
          if (ptrs.current.size === 2) {
            const [a, b] = Array.from(ptrs.current.values());
            const rect = e.currentTarget.getBoundingClientRect();
            const frac = clamp(((a + b) / 2 - rect.left) / plotW, 0, 1);
            pinch.current = { dist: Math.abs(a - b) || 1, n, i0, frac };
            drag.current = null;
          } else {
            drag.current = { x: e.clientX, i0 };
          }
        }}
        onPointerMove={(e) => {
          if (ptrs.current.has(e.pointerId)) ptrs.current.set(e.pointerId, e.clientX);
          const p = pinch.current;
          if (p && ptrs.current.size >= 2) {
            const [a, b] = Array.from(ptrs.current.values());
            applyZoom(p.n * (p.dist / (Math.abs(a - b) || 1)), p.frac, p.i0 + p.frac * p.n);
            return;
          }
          if (drag.current) {
            const i = clamp(drag.current.i0 + Math.round((drag.current.x - e.clientX) / cw), 0, data.length - n);
            if (i !== i0) setView({ i0: i, n });
            return;
          }
          const rect = e.currentTarget.getBoundingClientRect();
          const x = e.clientX - rect.left;
          setHover({ x, y: e.clientY - rect.top, i: clamp(Math.floor(x / cw), 0, vis.length - 1) });
        }}
        onPointerUp={endPointer}
        onPointerCancel={endPointer}
        onPointerLeave={(e) => { endPointer(e); setHover(null); }}
      >
        {/* horizontal gridlines */}
        {Array.from({ length: 5 }).map((_, i) => {
          const gy = padT + (chartH / 4) * i;
          const p = max - (range / 4) * i;
          return (
            <g key={i}>
              <line x1={0} y1={gy} x2={plotW} y2={gy} stroke="var(--color-line)" strokeOpacity={0.35} />
              <text x={w - padR + 6} y={gy + 3} fill="var(--color-faint)" fontSize={10} className="tnum">{p.toFixed(0)}</text>
            </g>
          );
        })}

        {/* date ticks — without them you lose your place once you zoom or pan */}
        {tickIdx.map((k, j) => (
          <text key={`t${j}`} x={clamp(k * cw + cw / 2, 12, plotW - 12)} y={height - 6}
            fill="var(--color-faint)" fontSize={9} textAnchor="middle" className="tnum">
            {vis[k]?.t?.slice(5)}
          </text>
        ))}

        {/* volume */}
        {vis.map((d, i) => {
          const vh = (d.volume / maxVol) * volH;
          return <rect key={`v${i}`} x={i * cw + (cw - bw) / 2} y={height - padB - vh} width={bw} height={vh} fill={d.close >= d.open ? upC : downC} opacity={0.22} rx={0.5} />;
        })}

        {/* candles */}
        {vis.map((d, i) => {
          const cx = i * cw + cw / 2;
          const c = d.close >= d.open ? upC : downC;
          const yo = y(d.open), yc = y(d.close);
          return (
            <g key={i}>
              <line x1={cx} y1={y(d.high)} x2={cx} y2={y(d.low)} stroke={c} strokeWidth={1} />
              <rect x={cx - bw / 2} y={Math.min(yo, yc)} width={bw} height={Math.max(1, Math.abs(yc - yo))} fill={c} rx={0.5} />
            </g>
          );
        })}

        {/* level lines. A crossed level is drawn BROKEN — dotted, faded, hollow price
            tag, struck-through label — so it reads as "this gave way", not as a level
            that quietly changed its name. */}
        {levels.map((l, i) => {
          const ly = y(l.price);
          const broken = !!l.crossed;
          const sw = 1 + (clamp(l.strength ?? 0, 0, 100) / 100) * 1.5;
          const band = l.lo != null && l.hi != null && l.hi > l.lo;
          const on = hitLevel === l;
          return (
            <g key={i}>
              {band && (
                <rect x={0} y={y(l.hi!)} width={plotW} height={Math.max(1, y(l.lo!) - y(l.hi!))}
                  fill={l.color} opacity={broken ? 0.05 : 0.09} />
              )}
              <line x1={0} y1={ly} x2={plotW} y2={ly} stroke={l.color} strokeWidth={sw}
                strokeDasharray={broken ? "1 5" : "4 4"} strokeOpacity={on ? 1 : broken ? 0.45 : 0.8} />
              {broken
                ? <rect x={w - padR + 0.5} y={ly - 8} width={padR - 1} height={16} fill="none" stroke={l.color} strokeOpacity={0.7} rx={3} />
                : <rect x={w - padR} y={ly - 8} width={padR} height={16} fill={l.color} rx={3} />}
              <text x={w - padR + 4} y={ly + 3} fill={broken ? l.color : "#08090c"} fontSize={9} fontWeight={700} className="tnum">
                {l.price.toFixed(0)}
              </text>
              <text x={4} y={ly - 4} fontSize={9} fontWeight={600} fill={l.color} opacity={broken ? 0.75 : 1}>
                <tspan style={broken ? { textDecoration: "line-through" } : undefined}>{l.label}</tspan>
                {broken && <tspan> · BROKEN</tspan>}
              </text>
            </g>
          );
        })}

        {/* live spot — solid, so every level reads as above or below the market */}
        {spot != null && Number.isFinite(spot) && (
          <g pointerEvents="none">
            <line x1={0} y1={y(spot)} x2={plotW} y2={y(spot)} stroke="var(--color-accent)" strokeWidth={1.25} strokeOpacity={0.9} />
            <rect x={w - padR} y={y(spot) - 8} width={padR} height={16} fill="var(--color-accent)" rx={3} />
            <text x={w - padR + 4} y={y(spot) + 3} fill="#08090c" fontSize={9} fontWeight={700} className="tnum">{spot.toFixed(0)}</text>
          </g>
        )}

        {/* crosshair */}
        {hover && (
          <g pointerEvents="none">
            <line x1={hover.i * cw + cw / 2} y1={padT} x2={hover.i * cw + cw / 2} y2={height - padB} stroke="var(--color-muted)" strokeDasharray="3 3" strokeOpacity={0.5} />
            <line x1={0} y1={hover.y} x2={plotW} y2={hover.y} stroke="var(--color-muted)" strokeDasharray="3 3" strokeOpacity={0.5} />
            <rect x={w - padR} y={hover.y - 8} width={padR} height={16} fill="var(--color-line)" rx={3} />
            <text x={w - padR + 4} y={hover.y + 3} fill="var(--color-frost)" fontSize={9} className="tnum">
              {(max - (hover.y - padT) / chartH * range).toFixed(0)}
            </text>
          </g>
        )}
      </svg>
    </div>
  );
}
