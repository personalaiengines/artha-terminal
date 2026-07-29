"use client";
import Link from "next/link";
import { Avatar } from "@/components/ui/primitives";
import { Sparkline } from "@/components/ui/sparkline";
import { DeltaPill } from "@/components/ui/stat";
import { Stock } from "@/lib/data";
import { inr } from "@/lib/format";

// Compact stock line used in movers, watchlist previews, portfolio snapshots.
// `sparkData` is real trailing closes supplied by the parent (see
// lib/use-sparklines.ts). Without it the sparkline is simply omitted — it
// used to be generated from the symbol name, which never moved with price.
export function StockRow({ stock, spark = true, sparkData }: { stock: Stock; spark?: boolean; sparkData?: number[] }) {
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
      {spark && sparkData && sparkData.length > 1 && (
        <div className="ml-auto hidden sm:block">
          <Sparkline data={sparkData} positive={sparkData[sparkData.length - 1] >= sparkData[0]} />
        </div>
      )}
      <div className="ml-auto flex flex-col items-end sm:ml-3">
        <span className="text-[13px] font-semibold text-frost tnum">{inr(stock.price)}</span>
        <DeltaPill value={stock.change} pct={stock.changePct} className="mt-0.5" />
      </div>
    </Link>
  );
}
