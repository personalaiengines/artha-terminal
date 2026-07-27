"use client";
import {
  Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis, CartesianGrid,
  PieChart, Pie, Cell, BarChart, Bar,
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
