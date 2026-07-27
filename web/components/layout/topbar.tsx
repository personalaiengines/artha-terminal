"use client";
import Link from "next/link";
import { Search, Bell, Menu } from "lucide-react";
import { useUI } from "./ui-store";
import { Kbd, LiveDot } from "@/components/ui/primitives";
import { IconButton } from "@/components/ui/button";
import { useApi } from "@/lib/use-api";
import { pct, trendClass } from "@/lib/format";
import { cn } from "@/lib/utils";

type GlobalRow = { name: string; price: number | null; changePct: number | null };

export function Topbar() {
  const { setCmdk } = useUI();
  const board = useApi<{ indices: GlobalRow[] } | null>("/api/global", null, (j) => (j.ok ? j : null));
  const indices = board?.indices ?? [];
  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-line bg-abyss/70 px-4 backdrop-blur-xl md:px-6">
      {/* Index ticker */}
      <div className="hidden items-center gap-4 overflow-hidden lg:flex">
        {indices.slice(0, 4).map((idx) => (
          <div key={idx.name} className="flex items-center gap-1.5 whitespace-nowrap text-[12px]">
            <span className="font-medium text-muted">{idx.name}</span>
            <span className="font-semibold text-frost tnum">{idx.price != null ? idx.price.toLocaleString("en-IN") : "—"}</span>
            <span className={cn("tnum font-medium", trendClass(idx.changePct ?? 0))}>{idx.changePct != null ? pct(idx.changePct) : "—"}</span>
          </div>
        ))}
      </div>

      <div className="ml-auto flex items-center gap-2">
        <button
          onClick={() => setCmdk(true)}
          className="group flex h-9 items-center gap-2 rounded-[var(--radius-sm)] bg-elevated px-3 hairline text-muted transition-colors hover:text-mist w-56 md:w-72"
        >
          <Search size={15} />
          <span className="text-[13px]">Search symbols, ask AI…</span>
          <span className="ml-auto flex items-center gap-0.5"><Kbd>⌘</Kbd><Kbd>K</Kbd></span>
        </button>

        <div className="hidden md:block"><LiveDot /></div>

        {/* Link, not <a><button> — a button nested in an anchor is invalid HTML
            and doesn't navigate reliably. */}
        <Link href="/alerts" aria-label="Alerts"
          className="inline-flex h-9 w-9 items-center justify-center rounded-[var(--radius-sm)] text-mist transition-colors hover:bg-raised hover:text-frost">
          <Bell size={17} />
        </Link>

        <Link href="/settings" aria-label="Account"
          className="h-8 w-8 rounded-full bg-gradient-to-br from-accent to-ai ring-focus transition-transform hover:scale-105" />
      </div>
    </header>
  );
}

export function MobileMenuButton() {
  return (
    <IconButton label="Menu" className="md:hidden"><Menu size={18} /></IconButton>
  );
}
