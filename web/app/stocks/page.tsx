"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Search, Download } from "lucide-react";
import { PageHeader } from "@/components/widgets/page-header";
import { Button } from "@/components/ui/button";
import { Segmented, Avatar } from "@/components/ui/primitives";
import { DataGrid, Column } from "@/components/ui/data-grid";
import { RatingBadge } from "@/components/ui/badge";
import { Sparkline } from "@/components/ui/sparkline";
import { series, Stock } from "@/lib/data";
import { useApi } from "@/lib/use-api";
import { inr, compactCr, pct, trendClass } from "@/lib/format";
import { cn } from "@/lib/utils";

export default function StocksScreener() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [seg, setSeg] = useState("all");
  const universe = useApi<Stock[]>("/api/universe", [], (j) => j.items);

  const rows = universe.filter((s) => {
    if (q && !(`${s.symbol} ${s.name}`.toLowerCase().includes(q.toLowerCase()))) return false;
    if (seg === "buy") return s.aiRating === "Strong Buy" || s.aiRating === "Buy";
    if (seg === "gainers") return s.changePct > 0;
    if (seg === "losers") return s.changePct < 0;
    return true;
  });

  // Export whatever is currently filtered/visible to CSV (client-side, no backend).
  const exportCsv = () => {
    const cols = ["symbol", "name", "sector", "price", "changePct", "mcapCr", "pe", "roe", "aiScore", "aiRating"];
    const csv = [cols.join(","), ...rows.map((s) => cols.map((c) => JSON.stringify((s as Record<string, unknown>)[c] ?? "")).join(","))].join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url; a.download = `artha-screener-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click(); URL.revokeObjectURL(url);
  };

  const columns: Column<Stock>[] = [
    { key: "symbol", header: "Company", width: "220px", sortable: true, sortValue: (s) => s.symbol,
      cell: (s) => <span className="flex items-center gap-2.5"><Avatar symbol={s.symbol} size={30} /><span className="min-w-0"><span className="block font-semibold text-frost leading-tight">{s.symbol}</span><span className="block text-[11px] text-muted truncate max-w-[140px]">{s.name}</span></span></span> },
    { key: "sector", header: "Sector", cell: (s) => <span className="text-mist text-[12px]">{s.sector}</span> },
    { key: "price", header: "Price", align: "right", sortable: true, sortValue: (s) => s.price, cell: (s) => <span className="tnum font-medium">{inr(s.price)}</span> },
    { key: "chg", header: "Chg%", align: "right", sortable: true, sortValue: (s) => s.changePct, cell: (s) => <span className={cn("tnum font-semibold", trendClass(s.changePct))}>{pct(s.changePct)}</span> },
    { key: "spark", header: "30D", align: "right", cell: (s) => <span className="inline-block"><Sparkline data={series(s.symbol.charCodeAt(0) + s.symbol.length, 30, s.price, 0.02)} positive={s.changePct >= 0} width={80} height={24} /></span> },
    { key: "mcap", header: "Mkt Cap", align: "right", sortable: true, sortValue: (s) => s.mcapCr, cell: (s) => <span className="tnum text-mist">₹{compactCr(s.mcapCr * 1e7)}</span> },
    { key: "pe", header: "P/E", align: "right", sortable: true, sortValue: (s) => s.pe, cell: (s) => <span className="tnum text-mist">{s.pe}</span> },
    { key: "roe", header: "ROE", align: "right", sortable: true, sortValue: (s) => s.roe, cell: (s) => <span className="tnum text-mist">{s.roe}%</span> },
    { key: "ai", header: "AI Score", align: "right", sortable: true, sortValue: (s) => s.aiScore, cell: (s) => <span className="tnum font-bold text-ai">{s.aiScore}</span> },
    { key: "rating", header: "Rating", align: "right", cell: (s) => <RatingBadge rating={s.aiRating} /> },
  ];

  return (
    <div>
      <PageHeader eyebrow="Trading" title="Stock Screener"
        description="Institutional-grade data grid across the ARTHA universe — sort, filter, and drill into any name."
        actions={<Button variant="secondary" size="sm" onClick={exportCsv}><Download size={14} />Export CSV</Button>} />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="flex h-9 items-center gap-2 rounded-[var(--radius-sm)] bg-elevated px-3 hairline w-full sm:w-72">
          <Search size={15} className="text-muted" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter symbols…" className="w-full bg-transparent text-[13px] text-frost outline-none placeholder:text-muted" />
        </div>
        <Segmented value={seg} onChange={setSeg} options={[
          { label: "All", value: "all" }, { label: "AI Buys", value: "buy" },
          { label: "Gainers", value: "gainers" }, { label: "Losers", value: "losers" },
        ]} />
        <span className="ml-auto text-[12px] text-muted tnum">{rows.length} instruments</span>
      </div>

      <DataGrid columns={columns} rows={rows} rowKey={(s) => s.symbol} onRowClick={(s) => router.push(`/stocks/${s.symbol}`)} />
    </div>
  );
}
