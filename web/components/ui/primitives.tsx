"use client";
import { cn } from "@/lib/utils";
import { ReactNode, useState } from "react";
import { motion } from "framer-motion";

export function SectionTitle({
  title, subtitle, action, className,
}: { title: string; subtitle?: string; action?: ReactNode; className?: string }) {
  return (
    <div className={cn("flex items-end justify-between gap-4 mb-4", className)}>
      <div>
        <h2 className="text-[19px] font-semibold text-frost tracking-tight">{title}</h2>
        {subtitle && <p className="text-[13px] text-muted mt-0.5">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="inline-flex h-5 min-w-5 items-center justify-center rounded-[5px] bg-raised px-1.5 text-[10px] font-medium text-muted hairline">
      {children}
    </kbd>
  );
}

export function Divider({ className }: { className?: string }) {
  return <div className={cn("h-px w-full bg-line", className)} />;
}

export function Segmented<T extends string>({
  options, value, onChange, size = "md",
}: { options: { label: string; value: T }[]; value: T; onChange: (v: T) => void; size?: "sm" | "md" }) {
  return (
    <div className={cn("inline-flex items-center gap-0.5 rounded-[var(--radius-sm)] bg-void p-0.5 hairline", size === "sm" && "text-[11px]")}>
      {options.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          className={cn(
            "relative rounded-[7px] px-3 py-1 font-medium transition-colors",
            size === "sm" ? "text-[11px]" : "text-[12px]",
            value === o.value ? "text-frost" : "text-muted hover:text-mist"
          )}
        >
          {value === o.value && (
            <motion.span layoutId="seg" className="absolute inset-0 rounded-[7px] bg-raised hairline" transition={{ type: "spring", stiffness: 400, damping: 32 }} />
          )}
          <span className="relative z-10">{o.label}</span>
        </button>
      ))}
    </div>
  );
}

export function Tabs({
  tabs, children,
}: { tabs: { id: string; label: string; icon?: ReactNode }[]; children: (active: string) => ReactNode }) {
  const [active, setActive] = useState(tabs[0].id);
  return (
    <div>
      <div className="flex items-center gap-1 border-b border-line mb-5 overflow-x-auto scrollbar-slim">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setActive(t.id)}
            className={cn(
              "relative flex items-center gap-1.5 whitespace-nowrap px-3.5 py-2.5 text-[13px] font-medium transition-colors",
              active === t.id ? "text-frost" : "text-muted hover:text-mist"
            )}
          >
            {t.icon}{t.label}
            {active === t.id && (
              <motion.span layoutId="tab-underline" className="absolute -bottom-px left-0 right-0 h-0.5 rounded-full bg-accent" transition={{ type: "spring", stiffness: 400, damping: 32 }} />
            )}
          </button>
        ))}
      </div>
      <motion.div key={active} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }}>
        {children(active)}
      </motion.div>
    </div>
  );
}

export function EmptyState({
  icon, title, description, action,
}: { icon: ReactNode; title: string; description: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="relative mb-5">
        <div className="absolute inset-0 blur-2xl bg-accent/20 rounded-full" />
        <div className="relative flex h-14 w-14 items-center justify-center rounded-[var(--radius-lg)] bg-elevated hairline text-accent">
          {icon}
        </div>
      </div>
      <h3 className="text-[15px] font-semibold text-frost">{title}</h3>
      <p className="text-[13px] text-muted mt-1.5 max-w-xs">{description}</p>
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("skeleton rounded-[var(--radius-sm)]", className)} />;
}

export function LiveDot({ label = "LIVE" }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[10.5px] font-semibold uppercase tracking-wider text-up">
      <span className="relative flex h-1.5 w-1.5">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-up opacity-70" />
        <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-up" />
      </span>
      {label}
    </span>
  );
}

export function Avatar({ symbol, size = 36 }: { symbol: string; size?: number }) {
  // Deterministic gradient monogram — company "branding" without external logos.
  const hue = [...symbol].reduce((a, c) => a + c.charCodeAt(0), 0) % 360;
  return (
    <div
      className="flex items-center justify-center rounded-[var(--radius-sm)] font-bold text-white shrink-0"
      style={{
        width: size, height: size, fontSize: size * 0.34,
        background: `linear-gradient(135deg, hsl(${hue} 62% 42%), hsl(${(hue + 40) % 360} 58% 30%))`,
      }}
    >
      {symbol.slice(0, 2)}
    </div>
  );
}
