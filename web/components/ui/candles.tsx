"use client";
import { useEffect, useRef, useState } from "react";

type Candle = { t: string; open: number; high: number; low: number; close: number; volume: number };
type Level = { price: number; label: string; color: string };

// Custom SVG candlestick with crosshair + level lines. No charting lib — full
// control of the TradingView-style dark aesthetic, and it's ~150 lines.
export function CandleChart({
  data, height = 360, levels = [],
}: { data: Candle[]; height?: number; levels?: Level[] }) {
  const wrap = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(900);
  const [hover, setHover] = useState<{ x: number; y: number; i: number } | null>(null);

  useEffect(() => {
    if (!wrap.current) return;
    const ro = new ResizeObserver(([e]) => setW(e.contentRect.width));
    ro.observe(wrap.current);
    return () => ro.disconnect();
  }, []);

  // No candles → don't compute an Infinity/NaN scale; show an honest empty state.
  if (!data.length) {
    return (
      <div ref={wrap} className="flex w-full items-center justify-center text-[12.5px] text-muted" style={{ height }}>
        No price history available.
      </div>
    );
  }

  const padR = 56, padB = 24, padT = 8;
  const volH = 56;
  const chartH = height - padB - volH;
  const plotW = w - padR;

  const prices = data.flatMap((d) => [d.high, d.low]);
  const lvlPrices = levels.map((l) => l.price);
  const min = Math.min(...prices, ...lvlPrices);
  const max = Math.max(...prices, ...lvlPrices);
  const range = max - min || 1;
  const maxVol = Math.max(...data.map((d) => d.volume));

  const y = (p: number) => padT + chartH - ((p - min) / range) * chartH;
  const cw = plotW / data.length;
  const bw = Math.max(1.5, cw * 0.62);

  const active = hover ? data[hover.i] : data[data.length - 1];
  const upC = "var(--color-up)", downC = "var(--color-down)";

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
      <svg
        width={w} height={height}
        onMouseMove={(e) => {
          const rect = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
          const x = e.clientX - rect.left;
          const i = Math.min(data.length - 1, Math.max(0, Math.floor(x / cw)));
          setHover({ x, y: e.clientY - rect.top, i });
        }}
        onMouseLeave={() => setHover(null)}
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

        {/* level lines (support/resistance/pivots) */}
        {levels.map((l, i) => (
          <g key={i}>
            <line x1={0} y1={y(l.price)} x2={plotW} y2={y(l.price)} stroke={l.color} strokeWidth={1} strokeDasharray="4 4" strokeOpacity={0.8} />
            <rect x={w - padR} y={y(l.price) - 8} width={padR} height={16} fill={l.color} rx={3} />
            <text x={w - padR + 4} y={y(l.price) + 3} fill="#08090c" fontSize={9} fontWeight={700} className="tnum">{l.price.toFixed(0)}</text>
            <text x={4} y={y(l.price) - 4} fill={l.color} fontSize={9} fontWeight={600}>{l.label}</text>
          </g>
        ))}

        {/* volume */}
        {data.map((d, i) => {
          const vh = (d.volume / maxVol) * volH;
          return <rect key={`v${i}`} x={i * cw + (cw - bw) / 2} y={height - padB - vh} width={bw} height={vh} fill={d.close >= d.open ? upC : downC} opacity={0.22} rx={0.5} />;
        })}

        {/* candles */}
        {data.map((d, i) => {
          const cx = i * cw + cw / 2;
          const isUp = d.close >= d.open;
          const c = isUp ? upC : downC;
          const yo = y(d.open), yc = y(d.close);
          return (
            <g key={i}>
              <line x1={cx} y1={y(d.high)} x2={cx} y2={y(d.low)} stroke={c} strokeWidth={1} />
              <rect x={cx - bw / 2} y={Math.min(yo, yc)} width={bw} height={Math.max(1, Math.abs(yc - yo))} fill={c} rx={0.5} />
            </g>
          );
        })}

        {/* crosshair */}
        {hover && (
          <g pointerEvents="none">
            <line x1={hover.i * cw + cw / 2} y1={padT} x2={hover.i * cw + cw / 2} y2={height - padB} stroke="var(--color-muted)" strokeDasharray="3 3" strokeOpacity={0.5} />
            <line x1={0} y1={hover.y} x2={plotW} y2={hover.y} stroke="var(--color-muted)" strokeDasharray="3 3" strokeOpacity={0.5} />
          </g>
        )}
      </svg>
    </div>
  );
}
