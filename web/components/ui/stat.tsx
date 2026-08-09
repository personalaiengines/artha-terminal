"use client";
import { motion, useInView } from "framer-motion";
import { useRef } from "react";
import { ArrowUpRight, ArrowDownRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { useUI } from "@/components/layout/ui-store";

// Headline metric number. Renders the value, and nothing else.
//
// This used to count up from 0 over 0.9s via framer-motion, gated on
// `useInView(ref, { once: true })`. That decoration cost three separate money
// bugs and is gone:
//
//   * the ref was attached only on the non-null branch, so while data loaded the
//     IntersectionObserver had no node; with `once: true` it never re-subscribed
//     and the count-up never started, leaving the initial `useState(0)` on screen;
//   * `display ?? safe` only guards null — the animation's first frame sets 0,
//     and `0 ?? safe` is 0, so an interrupted animation stuck at zero;
//   * even working perfectly, it displays numbers that are simply false for up
//     to a second, and any throttling (background tab, slow device, a re-render
//     mid-flight) leaves one of them on screen.
//
// A ₹1,842 Value at Risk rendered as ₹0 next to its own correct sub-label. On a
// screen whose entire purpose is telling someone what they stand to lose, a
// number that animates is worth less than a number that is right.
//
// The name and props are unchanged so no caller had to move.
export function AnimatedNumber({
  value, decimals = 2, prefix = "", suffix = "", className,
}: { value: number | null | undefined; decimals?: number; prefix?: string; suffix?: string; className?: string }) {
  const safe = typeof value === "number" && Number.isFinite(value) ? value : null;
  return (
    <span className={cn("tnum", className)}>
      {safe === null ? "—" : (
        <>
          {prefix}
          {safe.toLocaleString("en-IN", { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}
          {suffix}
        </>
      )}
    </span>
  );
}

export function DeltaPill({ value, pct, className }: { value?: number | null; pct: number | null | undefined; className?: string }) {
  const { changeMode } = useUI();
  const p = typeof pct === "number" && Number.isFinite(pct) ? pct : 0;
  const up = p >= 0;
  const hasAbs = typeof value === "number" && Number.isFinite(value);
  // "abs" mode shows the ₹ change instead of %, only when an absolute value
  // was actually given — generic (non-price) deltas that don't pass `value`
  // always fall back to % since there's nothing to toggle to.
  const showAbs = changeMode === "abs" && hasAbs;
  return (
    <span className={cn(
      "inline-flex items-center gap-0.5 rounded-md px-1.5 py-0.5 text-[12px] font-semibold tnum",
      up ? "bg-up-soft/50 text-up" : "bg-down-soft/50 text-down", className
    )}>
      {up ? <ArrowUpRight size={13} strokeWidth={2.6} /> : <ArrowDownRight size={13} strokeWidth={2.6} />}
      {showAbs ? `₹${Math.abs(value as number).toFixed(2)}` : `${Math.abs(p).toFixed(2)}%`}
    </span>
  );
}

export function Stat({
  label, value, delta, prefix, suffix, decimals = 2, sub, className,
}: {
  label: string; value: number | null | undefined; delta?: number;
  prefix?: string; suffix?: string; decimals?: number; sub?: string; className?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <span className="text-[11px] font-medium text-muted uppercase tracking-wide">{label}</span>
      <div className="flex items-baseline gap-2 flex-wrap">
        <span className="text-[22px] font-semibold text-frost tracking-tight">
          <AnimatedNumber value={value} decimals={decimals} prefix={prefix} suffix={suffix} />
        </span>
        {delta !== undefined && <DeltaPill pct={delta} />}
      </div>
      {sub && <span className="text-[11px] text-muted">{sub}</span>}
    </div>
  );
}

// Circular 0-10 / 0-100 score ring, colored by band.
//
// `tone="risk"` inverts the band. The default reads high-is-good, which is right
// for a health score and exactly backwards for a risk score — an 8.7/10 risk
// book was rendering a green ring next to the word "Elevated".
export function ScoreRing({
  value, max = 10, size = 68, label, tone,
}: {
  value: number | null | undefined; max?: number; size?: number; label?: string;
  tone?: "ai" | "auto" | "risk";
}) {
  const ref = useRef<SVGSVGElement>(null);
  const inView = useInView(ref, { once: true });
  const known = typeof value === "number" && Number.isFinite(value);
  const safe = known ? (value as number) : 0;
  const pct = Math.min(1, safe / max);
  const r = (size - 8) / 2;
  const c = 2 * Math.PI * r;
  // An unknown score is not a zero one: draw the track only, and print an em
  // dash, rather than a confident "0.0" in whichever colour zero happens to hit.
  const color = !known ? "var(--color-line)"
    : tone === "ai" ? "var(--color-ai)"
      : tone === "risk"
        ? (pct >= 0.7 ? "var(--color-down)" : pct >= 0.4 ? "var(--color-warn)" : "var(--color-up)")
        : pct >= 0.75 ? "var(--color-up)" : pct >= 0.5 ? "var(--color-warn)" : "var(--color-down)";
  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg ref={ref} width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--color-line)" strokeWidth={4} />
        <motion.circle
          cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={4}
          strokeLinecap="round" strokeDasharray={c}
          initial={{ strokeDashoffset: c }}
          animate={inView ? { strokeDashoffset: c * (1 - (known ? pct : 0)) } : {}}
          transition={{ duration: 1, ease: [0.22, 1, 0.36, 1] }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-[15px] font-bold text-frost tnum leading-none">{known ? safe.toFixed(1) : "—"}</span>
        {label && <span className="text-[8.5px] text-muted uppercase mt-0.5 tracking-wider">{label}</span>}
      </div>
    </div>
  );
}

export function HealthBar({ value }: { value: number | null | undefined }) {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true });
  const v = typeof value === "number" && Number.isFinite(value) ? value : 0;
  const color = v >= 70 ? "var(--color-up)" : v >= 45 ? "var(--color-warn)" : "var(--color-down)";
  return (
    <div ref={ref} className="h-1.5 w-full rounded-full bg-line overflow-hidden">
      <motion.div
        className="h-full rounded-full"
        style={{ background: color }}
        initial={{ width: 0 }}
        animate={inView ? { width: `${v}%` } : {}}
        transition={{ duration: 0.9, ease: [0.22, 1, 0.36, 1] }}
      />
    </div>
  );
}
