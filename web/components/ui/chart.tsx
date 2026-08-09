"use client";
import {
  Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis, CartesianGrid,
  PieChart, Pie, Cell, BarChart, Bar, Line, LineChart, ReferenceLine,
} from "recharts";
import { ReactNode } from "react";

const AXIS = { stroke: "var(--color-faint)", fontSize: 10, tickLine: false, axisLine: false };
const GRID = { stroke: "var(--color-line)", strokeDasharray: "0", vertical: false, opacity: 0.4 };

function TooltipBox({ children }: { children: ReactNode }) {
  return (
    <div className="glass rounded-[var(--radius-sm)] hairline px-3 py-2 shadow-[var(--shadow-lg)] text-[12px]">
      {children}
    </div>
  );
}

// Premium gradient price area — the app-wide default for any single series.
export function AreaPrice({
  data, dataKey = "close", xKey = "t", height = 240, up = true, showAxes = true,
  valueFmt = (v: number) => v.toLocaleString("en-IN"),
}: {
  data: Record<string, unknown>[]; dataKey?: string; xKey?: string; height?: number;
  up?: boolean; showAxes?: boolean; valueFmt?: (v: number) => string;
}) {
  const color = up ? "var(--color-up)" : "var(--color-down)";
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 8, right: 4, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id={`ap-${dataKey}-${up}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.28} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid {...GRID} />
        {showAxes && <XAxis dataKey={xKey} {...AXIS} minTickGap={40} />}
        {showAxes && <YAxis {...AXIS} domain={["auto", "auto"]} width={44} orientation="right" tickFormatter={(v) => valueFmt(Number(v))} />}
        <Tooltip
          cursor={{ stroke: "var(--color-muted)", strokeDasharray: "3 3" }}
          content={({ active, payload, label }) =>
            active && payload?.length ? (
              <TooltipBox>
                <div className="text-muted mb-0.5">{String(label)}</div>
                <div className="font-semibold text-frost tnum">{valueFmt(Number(payload[0].value))}</div>
              </TooltipBox>
            ) : null
          }
        />
        <Area type="monotone" dataKey={dataKey} stroke={color} strokeWidth={2} fill={`url(#ap-${dataKey}-${up})`} animationDuration={900} dot={false} activeDot={{ r: 3, fill: color, stroke: "var(--color-abyss)", strokeWidth: 2 }} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

// Several series on one set of axes, for comparing things measured in
// different units (index levels rebased to a common start). Distinct from
// AreaPrice, which is deliberately single-series and gradient-filled.
// `baseline` and `tooltipFmt` default to the rebased-index reading this was
// built for (baseline 100, tooltip as % from it). Pass baseline={null} and a
// tooltipFmt for a series measured in its own units — IV points, P/L.
export function MultiLine({
  data, series, xKey = "t", height = 260,
  valueFmt = (v: number) => v.toFixed(1),
  baseline = 100,
  tooltipFmt = (v: number) => `${v - 100 >= 0 ? "+" : ""}${(v - 100).toFixed(2)}%`,
}: {
  data: Record<string, unknown>[];
  series: { key: string; label: string; color: string }[];
  xKey?: string; height?: number; valueFmt?: (v: number) => string;
  baseline?: number | null; tooltipFmt?: (v: number) => string;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 4, left: 0, bottom: 0 }}>
        <CartesianGrid {...GRID} />
        <XAxis dataKey={xKey} {...AXIS} minTickGap={48} />
        <YAxis {...AXIS} domain={["auto", "auto"]} width={44} orientation="right"
               tickFormatter={(v) => valueFmt(Number(v))} />
        {baseline !== null &&
          <ReferenceLine y={baseline} stroke="var(--color-line)" strokeDasharray="3 3" ifOverflow="extendDomain" />}
        <Tooltip
          cursor={{ stroke: "var(--color-muted)", strokeDasharray: "3 3" }}
          content={({ active, payload, label }) =>
            active && payload?.length ? (
              <TooltipBox>
                <div className="mb-1 text-muted">{String(label)}</div>
                {payload.map((p) => (
                  <div key={String(p.dataKey)} className="flex items-center gap-2">
                    <span className="h-2 w-2 rounded-full" style={{ background: p.color as string }} />
                    <span className="text-mist">{series.find((s) => s.key === p.dataKey)?.label}</span>
                    <span className="ml-auto font-semibold text-frost tnum">
                      {p.value == null ? "—" : tooltipFmt(Number(p.value))}
                    </span>
                  </div>
                ))}
              </TooltipBox>
            ) : null
          }
        />
        {series.map((s) => (
          <Line key={s.key} type="monotone" dataKey={s.key} stroke={s.color} strokeWidth={2}
                dot={false} animationDuration={900}
                activeDot={{ r: 3, fill: s.color, stroke: "var(--color-abyss)", strokeWidth: 2 }} />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

export function Donut({
  data, height = 200, centerLabel, centerValue,
}: {
  data: { name: string; value: number; color: string }[];
  height?: number; centerLabel?: string; centerValue?: string;
}) {
  return (
    <div className="relative" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie data={data} dataKey="value" nameKey="name" innerRadius="66%" outerRadius="92%" paddingAngle={2} stroke="none" animationDuration={800}>
            {data.map((d, i) => <Cell key={i} fill={d.color} />)}
          </Pie>
          <Tooltip content={({ active, payload }) =>
            active && payload?.length ? (
              <TooltipBox><span className="font-semibold text-frost">{payload[0].name}</span> <span className="text-muted">· {Number(payload[0].value).toFixed(1)}%</span></TooltipBox>
            ) : null
          } />
        </PieChart>
      </ResponsiveContainer>
      {(centerLabel || centerValue) && (
        <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
          {centerValue && <span className="text-[19px] font-bold text-frost tnum">{centerValue}</span>}
          {centerLabel && <span className="text-[10px] text-muted uppercase tracking-wide">{centerLabel}</span>}
        </div>
      )}
    </div>
  );
}

// Cumulative curve against a zero baseline. Single series on purpose: the
// reader's job is "where is the running total now", and a second scale on the
// same axes would invent a relationship the data doesn't have. Sign is carried
// by position relative to the zero rule, not by the fill alone.
export function ZeroArea({
  data, dataKey = "v", xKey = "t", height = 240,
  color = "var(--color-accent)",
  valueFmt = (v: number) => v.toLocaleString("en-IN"),
  label = "Value",
}: {
  data: Record<string, unknown>[]; dataKey?: string; xKey?: string; height?: number;
  color?: string; valueFmt?: (v: number) => string; label?: string;
}) {
  const id = `za-${dataKey}`;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 8, right: 6, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.3} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid {...GRID} />
        <XAxis dataKey={xKey} {...AXIS} minTickGap={44} />
        <YAxis {...AXIS} width={52} orientation="right" domain={["auto", "auto"]}
               tickFormatter={(v) => valueFmt(Number(v))} />
        <ReferenceLine y={0} stroke="var(--color-line)" ifOverflow="extendDomain" />
        <Tooltip
          cursor={{ stroke: "var(--color-muted)", strokeWidth: 1 }}
          content={({ active, payload, label: l }) =>
            active && payload?.length ? (
              <TooltipBox>
                <div className="mb-0.5 text-muted">{String(l)}</div>
                <div className="flex items-center gap-2">
                  <span className="h-2 w-2 rounded-full" style={{ background: color }} />
                  <span className="text-mist">{label}</span>
                  <span className="ml-auto font-semibold text-frost tnum">{valueFmt(Number(payload[0].value))}</span>
                </div>
              </TooltipBox>
            ) : null
          }
        />
        <Area type="monotone" dataKey={dataKey} stroke={color} strokeWidth={2}
              fill={`url(#${id})`} dot={false} animationDuration={800}
              activeDot={{ r: 4, fill: color, stroke: "var(--color-elevated)", strokeWidth: 2 }} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

// Vertical columns diverging around zero — per-session P&L. Above/below the
// zero rule is the primary encoding of sign; the up/down colors reinforce it
// but never carry it alone (they are 3.8 ΔE apart under deuteranopia, so a
// red/green-only chart is unreadable for a red-green colorblind reader).
export function ZeroColumns({
  data, dataKey = "v", xKey = "t", height = 200,
  valueFmt = (v: number) => v.toLocaleString("en-IN"),
}: {
  data: Record<string, unknown>[]; dataKey?: string; xKey?: string;
  height?: number; valueFmt?: (v: number) => string;
}) {
  // Rounded far-from-zero end only — the end that touches the baseline stays
  // square, so the bar reads as anchored rather than floating.
  const RoundedEnd = (p: any) => {
    const { x, y, width, height: h, fill } = p;
    if (!h) return <g />;
    const r = Math.min(4, width / 2, Math.abs(h));
    const up = (p[dataKey] ?? 0) >= 0;
    const d = up
      ? `M${x},${y + h} L${x},${y + r} Q${x},${y} ${x + r},${y} L${x + width - r},${y} Q${x + width},${y} ${x + width},${y + r} L${x + width},${y + h} Z`
      : `M${x},${y} L${x},${y + h - r} Q${x},${y + h} ${x + r},${y + h} L${x + width - r},${y + h} Q${x + width},${y + h} ${x + width},${y + h - r} L${x + width},${y} Z`;
    return <path d={d} fill={fill} />;
  };

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 6, left: 0, bottom: 0 }} barCategoryGap="18%">
        <CartesianGrid {...GRID} />
        <XAxis dataKey={xKey} {...AXIS} minTickGap={44} />
        <YAxis {...AXIS} width={52} orientation="right" tickFormatter={(v) => valueFmt(Number(v))} />
        <ReferenceLine y={0} stroke="var(--color-line)" ifOverflow="extendDomain" />
        <Tooltip
          cursor={{ fill: "var(--color-raised)", opacity: 0.35 }}
          content={({ active, payload, label }) =>
            active && payload?.length ? (
              <TooltipBox>
                <div className="mb-0.5 text-muted">{String(label)}</div>
                <div className="font-semibold text-frost tnum">{valueFmt(Number(payload[0].value))}</div>
              </TooltipBox>
            ) : null
          }
        />
        <Bar dataKey={dataKey} shape={RoundedEnd} animationDuration={800} maxBarSize={22}>
          {data.map((d, i) => (
            <Cell key={i} fill={Number(d[dataKey]) >= 0 ? "var(--color-up)" : "var(--color-down)"} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

// Horizontal diverging bars — OI, gainers/losers, attribution.
export function HBars({
  data, height = 220, fmt = (v: number) => String(v),
}: { data: { name: string; value: number; color?: string }[]; height?: number; fmt?: (v: number) => string }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} layout="vertical" margin={{ left: 0, right: 8, top: 0, bottom: 0 }}>
        <XAxis type="number" hide />
        <YAxis type="category" dataKey="name" {...AXIS} width={74} />
        <Tooltip cursor={{ fill: "var(--color-raised)", opacity: 0.4 }} content={({ active, payload, label }) =>
          active && payload?.length ? <TooltipBox><span className="text-muted">{String(label)}</span> <span className="font-semibold text-frost tnum">{fmt(Number(payload[0].value))}</span></TooltipBox> : null
        } />
        <Bar dataKey="value" radius={[0, 4, 4, 0]} animationDuration={800} barSize={14}>
          {data.map((d, i) => <Cell key={i} fill={d.color ?? (d.value >= 0 ? "var(--color-up)" : "var(--color-down)")} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
