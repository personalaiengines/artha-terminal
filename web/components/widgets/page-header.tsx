"use client";
import { motion } from "framer-motion";
import { ReactNode } from "react";

// Every page opens with this. Uniform title scale, spacing, and action slot →
// no page invents its own header.
export function PageHeader({
  eyebrow, title, description, actions,
}: { eyebrow?: string; title: string; description?: string; actions?: ReactNode }) {
  return (
    <div className="mb-7 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
      <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }}>
        {eyebrow && <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.16em] text-accent">{eyebrow}</div>}
        <h1 className="text-[26px] font-bold tracking-tight text-frost leading-none md:text-[30px]">{title}</h1>
        {description && <p className="mt-2 text-[14px] text-muted max-w-2xl">{description}</p>}
      </motion.div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}
