"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Plus, Pin, Search } from "lucide-react";
import { PageHeader } from "@/components/widgets/page-header";
import { Button } from "@/components/ui/button";
import { Segmented, Avatar } from "@/components/ui/primitives";
import { DataGrid, Column } from "@/components/ui/data-grid";
import { RatingBadge, Badge } from "@/components/ui/badge";
import { Sparkline } from "@/components/ui/sparkline";
import { series, Stock } from "@/lib/data";
import { useApi } from "@/lib/use-api";
import { inr, compactCr, pct, trendClass } from "@/lib/format";
import { cn } from "@/lib/utils";

const LISTS: Record<string, string[]> = {
  "Core Holdings": ["RELIANCE", "HDFCBANK", "INFY", "TCS", "ICICIBANK", "LT"],
  "High Conviction": ["BAJFINANCE", "TITAN", "BHARTIARTL", "SBIN", "ADANIENT"],
  "Watch & Wait": ["TATAMOTORS", "WIPRO", "ASIANPAINT", "HINDUNILVR", "ITC", "NTPC", "MARUTI"],
};

export default function Watchlists() {
  const router = useRouter();
  const [list, setList] = useState("Core Holdings");
  const [pinned, setPinned] = useState<Set<string>>(new Set(["RELIANCE"]));
  const [q, setQ] = useState("");
  const universe = useApi<Stock[]>("/api/universe", [], (j) => j.items);

  const rows = universe
    .filter((s) => LISTS[list].includes(s.symbol))
    .filter((s) => !q || `${s.symbol} ${s.name}`.toLowerCase().includes(q.toLowerCase()))
    .sort((a, b) => (pinned.has(b.symbol) ? 1 : 0) - (pinned.has(a.symbol) ? 1 : 0));

  const togglePin = (sym: string) => setPinned((p) => { const n = new Set(p); n.has(sym) ? n.delete(sym) : n.add(sym); return n; });

  const columns: Column<Stock>[] = [
    { key: "pin", header: "", width: "36px", cell: (s) => <button onClick={(e) => { e.stopPropagation(); togglePin(s.symbol); }} className={cn("transition-colors", pinned.has(s.symbol) ? "text-warn" : "text-faint hover:text-muted")}><Pin size={14} fill={pinned.has(s.symbol) ? "currentColor" : "none"} /></button> },
    { key: "symbol", header: "Symbol", width: "200px", sortable: true, sortValue: (s) => s.symbol, cell: (s) => <span className="flex items-center gap-2.5"><Avatar symbol={s.symbol} size={28} /><span><span className="block font-semibold text-frost leading-tight">{s.symbol}</span><span className="block text-[11px] text-muted truncate max-w-[130px]">{s.name}</span></span></span> },
    { key: "sector", header: "Sector", cell: (s) => <Badge tone="neutral">{s.sector}</Badge> },
    { key: "price", header: "LTP", align: "right", sortable: true, sortValue: (s) => s.price, cell: (s) => <span className="tnum font-medium">{inr(s.price)}</span> },
    { key: "chg", header: "Chg%", align: "right", sortable: true, sortValue: (s) => s.changePct, cell: (s) => <span className={cn("tnum font-semibold", trendClass(s.changePct))}>{pct(s.changePct)}</span> },
    { key: "spark", header: "Trend", align: "right", cell: (s) => <span className="inline-block"><Sparkline data={series(s.symbol.charCodeAt(0) + s.symbol.length, 30, s.price, 0.02)} positive={s.changePct >= 0} width={84} height={24} /></span> },
    { key: "vol", header: "Volume", align: "right", sortable: true, sortValue: (s) => s.volume, cell: (s) => { const spike = s.volume > 4e6; return <span className={cn("tnum", spike ? "text-warn font-semibold" : "text-mist")}>{compactCr(s.volume)}{spike && " ⚡"}</span>; } },
    { key: "mcap", header: "Mkt Cap", align: "right", sortable: true, sortValue: (s) => s.mcapCr, cell: (s) => <span className="tnum text-mist">₹{compactCr(s.mcapCr * 1e7)}</span> },
    { key: "ai", header: "AI", align: "right", sortable: true, sortValue: (s) => s.aiScore, cell: (s) => <span className="tnum font-bold text-ai">{s.aiScore}</span> },
    { key: "rating", header: "Rating", align: "right", cell: (s) => <RatingBadge rating={s.aiRating} /> },
  ];

  return (
    <div>
      <PageHeader eyebrow="Workspace" title="Watchlists"
        description="Institutional-grade tracking grids. Pin, sort, and monitor volume spikes across your lists."
        actions={<Button variant="secondary" size="sm"><Plus size={14} />New List</Button>} />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Segmented value={list} onChange={setList} options={Object.keys(LISTS).map((l) => ({ label: l, value: l }))} />
        <div className="flex h-9 items-center gap-2 rounded-[var(--radius-sm)] bg-elevated px-3 hairline sm:ml-auto w-full sm:w-60">
          <Search size={15} className="text-muted" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter…" className="w-full bg-transparent text-[13px] text-frost outline-none placeholder:text-muted" />
        </div>
      </div>

      <DataGrid columns={columns} rows={rows} rowKey={(s) => s.symbol} onRowClick={(s) => router.push(`/stocks/${s.symbol}`)} pinnedFirstCol={false} />
    </div>
  );
}
