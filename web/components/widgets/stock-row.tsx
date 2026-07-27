"use client";
import Link from "next/link";
import { Avatar } from "@/components/ui/primitives";
import { Sparkline } from "@/components/ui/sparkline";
import { DeltaPill } from "@/components/ui/stat";
import { Stock, series } from "@/lib/data";
import { inr } from "@/lib/format";

// Compact stock line used in movers, watchlist previews, portfolio snapshots.
export function StockRow({ stock, spark = true }: { stock: Stock; spark?: boolean }) {
  return (
    <Link
      href={`/stocks/${stock.symbol}`}
      className="flex items-center gap-3 rounded-[var(--radius-sm)] px-2.5 py-2 transition-colors hover:bg-raised/60"
    >
      <Avatar symbol={stock.symbol} size={32} />
      <div className="min-w-0">
        <div className="text-[13px] font-semibold text-frost leading-tight">{stock.symbol}</div>
        <div className="text-[11px] text-muted truncate max-w-[120px]">{stock.name}</div>
      </div>
      {spark && (
        <div className="ml-auto hidden sm:block">
          <Sparkline data={series(stock.symbol.charCodeAt(0) + stock.symbol.length, 24, stock.price, 0.02)} positive={stock.changePct >= 0} />
        </div>
      )}
      <div className="ml-auto flex flex-col items-end sm:ml-3">
        <span className="text-[13px] font-semibold text-frost tnum">{inr(stock.price)}</span>
        <DeltaPill pct={stock.changePct} className="mt-0.5" />
      </div>
    </Link>
  );
}
