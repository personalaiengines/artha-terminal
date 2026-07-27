"use client";
import { motion, type HTMLMotionProps } from "framer-motion";
import { cn } from "@/lib/utils";
import { ReactNode } from "react";

type Variant = "primary" | "secondary" | "ghost" | "ai" | "danger";
type Size = "sm" | "md" | "lg" | "icon";

const V: Record<Variant, string> = {
  primary: "bg-accent text-white hover:bg-[color-mix(in_oklab,var(--color-accent)_88%,white)] shadow-[0_4px_16px_-4px_rgba(59,130,246,0.5)]",
  secondary: "bg-raised text-frost hairline hover:bg-line",
  ghost: "text-mist hover:bg-raised hover:text-frost",
  ai: "bg-ai text-white hover:bg-[color-mix(in_oklab,var(--color-ai)_88%,white)] shadow-[0_4px_18px_-4px_rgba(139,92,246,0.55)]",
  danger: "bg-down text-white hover:opacity-90",
};
const S: Record<Size, string> = {
  sm: "h-8 px-3 text-[12px] gap-1.5 rounded-[var(--radius-sm)]",
  md: "h-9 px-4 text-[13px] gap-2 rounded-[var(--radius-sm)]",
  lg: "h-11 px-6 text-[14px] gap-2 rounded-[var(--radius-md)]",
  icon: "h-9 w-9 rounded-[var(--radius-sm)] justify-center",
};

export function Button({
  variant = "secondary",
  size = "md",
  className,
  children,
  ...props
}: { variant?: Variant; size?: Size } & HTMLMotionProps<"button">) {
  return (
    <motion.button
      whileTap={{ scale: 0.96 }}
      transition={{ duration: 0.15 }}
      className={cn(
        "inline-flex items-center font-medium ring-focus transition-colors select-none",
        "disabled:opacity-40 disabled:pointer-events-none",
        V[variant], S[size], className
      )}
      {...props}
    >
      {children}
    </motion.button>
  );
}

export function IconButton({
  children, label, className, ...props
}: { children: ReactNode; label: string } & HTMLMotionProps<"button">) {
  return (
    <Button variant="ghost" size="icon" aria-label={label} className={className} {...props}>
      {children}
    </Button>
  );
}
