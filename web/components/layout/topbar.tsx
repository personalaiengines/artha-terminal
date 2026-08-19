"use client";
import Link from "next/link";
import { Search, Bell, Menu } from "lucide-react";
import { useUI } from "./ui-store";
import { Kbd, LiveDot, Segmented } from "@/components/ui/primitives";
import { IconButton } from "@/components/ui/button";
import { IndexTicker } from "@/components/widgets/india-indices";
import { AccountMenu } from "./account-menu";

export function Topbar() {
  const { setCmdk, changeMode, setChangeMode } = useUI();
  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-line bg-abyss/70 px-4 backdrop-blur-xl md:px-6">
      {/* Scrolling index tape — sits in the chrome next to search/alerts/avatar,
          so it's on every page rather than only the dashboard. Was four static
          GLOBAL indices (S&P, Nasdaq …) on a terminal for Indian equities. */}
      <div className="hidden min-w-0 flex-1 lg:block">
        <IndexTicker variant="bare" />
      </div>

      <div className="ml-auto flex shrink-0 items-center gap-2">
        <Segmented size="sm" value={changeMode} onChange={setChangeMode}
          options={[{ label: "%", value: "pct" }, { label: "₹", value: "abs" }]} />

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

        <AccountMenu />
      </div>
    </header>
  );
}

export function MobileMenuButton() {
  return (
    <IconButton label="Menu" className="md:hidden"><Menu size={18} /></IconButton>
  );
}
