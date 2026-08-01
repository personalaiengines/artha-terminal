"use client";
import { animate, motion, useInView } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import { ArrowUpRight, ArrowDownRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { useUI } from "@/components/layout/ui-store";

// Count-up number. Used for every headline metric so animation is uniform.
export function AnimatedNumber({
  value, decimals = 2, prefix = "", suffix = "", className,
}: { value: number | null | undefined; decimals?: number; prefix?: string; suffix?: string; className?: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true, margin: "-40px" });
  const [display, setDisplay] = useState(0);
  const safe = typeof value === "number" && Number.isFinite(value) ? value : null;

  useEffect(() => {
    if (!inView || safe === null) return;
    const controls = animate(0, safe, {
      duration: 0.9, ease: [0.22, 1, 0.36, 1],
      onUpdate: (v) => setDisplay(v),
    });
    return () => controls.stop();
  }, [inView, safe]);

  if (safe === null) return <span className={cn("tnum", className)}>—</span>;
  return (
    <span ref={ref} className={cn("tnum", className)}>
      {prefix}
      {display.toLocaleString("en-IN", { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}
      {suffix}
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
export function ScoreRing({
  value, max = 10, size = 68, label, tone,
}: { value: number | null | undefined; max?: number; size?: number; label?: string; tone?: "ai" | "auto" }) {
  const ref = useRef<SVGSVGElement>(null);
  const inView = useInView(ref, { once: true });
  const safe = typeof value === "number" && Number.isFinite(value) ? value : 0;
  const pct = Math.min(1, safe / max);
  const r = (size - 8) / 2;
  const c = 2 * Math.PI * r;
  const color = tone === "ai" ? "var(--color-ai)"
    : pct >= 0.75 ? "var(--color-up)" : pct >= 0.5 ? "var(--color-warn)" : "var(--color-down)";
  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg ref={ref} width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--color-line)" strokeWidth={4} />
        <motion.circle
          cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={4}
          strokeLinecap="round" strokeDasharray={c}
          initial={{ strokeDashoffset: c }}
          animate={inView ? { strokeDashoffset: c * (1 - pct) } : {}}
          transition={{ duration: 1, ease: [0.22, 1, 0.36, 1] }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-[15px] font-bold text-frost tnum leading-none">{safe.toFixed(1)}</span>
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
