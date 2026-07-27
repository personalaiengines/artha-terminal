"use client";
import { motion, type HTMLMotionProps } from "framer-motion";
import { cn } from "@/lib/utils";
import { ReactNode } from "react";

// The single card surface. Every panel in the app is one of these variants —
// change the look here and the whole product shifts together.
type Variant = "default" | "elevated" | "glass" | "ai" | "flush";

const VARIANTS: Record<Variant, string> = {
  default: "bg-elevated hairline",
  elevated: "bg-elevated hairline-strong shadow-[var(--shadow-md)]",
  glass: "glass hairline shadow-[var(--shadow-md)]",
  ai: "bg-[color-mix(in_oklab,var(--color-ai-soft)_28%,var(--color-elevated))] hairline shadow-[var(--shadow-glow-ai)]",
  flush: "bg-surface hairline",
};

export function Card({
  variant = "default",
  interactive = false,
  className,
  children,
  delay = 0,
  ...props
}: {
  variant?: Variant;
  interactive?: boolean;
  delay?: number;
} & HTMLMotionProps<"div">) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1], delay }}
      whileHover={interactive ? { y: -3 } : undefined}
      className={cn(
        "rounded-[var(--radius-lg)]",
        VARIANTS[variant],
        interactive && "cursor-pointer transition-shadow hover:shadow-[var(--shadow-lg)]",
        className
      )}
      {...props}
    >
      {children}
    </motion.div>
  );
}

export function CardHeader({
  title,
  subtitle,
  icon,
  action,
  className,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  icon?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex items-start justify-between gap-3 px-5 pt-4 pb-3", className)}>
      <div className="flex items-center gap-2.5 min-w-0">
        {icon && <span className="text-muted shrink-0">{icon}</span>}
        <div className="min-w-0">
          <h3 className="text-[13px] font-semibold text-frost tracking-tight truncate">{title}</h3>
          {subtitle && <p className="text-[11px] text-muted mt-0.5 truncate">{subtitle}</p>}
        </div>
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

export function CardBody({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn("px-5 pb-5", className)}>{children}</div>;
}
