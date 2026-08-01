"use client";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Search, Download, X } from "lucide-react";
import { PageHeader } from "@/components/widgets/page-header";
import { Button } from "@/components/ui/button";
import { Segmented, Avatar } from "@/components/ui/primitives";
import { DataGrid, Column } from "@/components/ui/data-grid";
import { RatingBadge } from "@/components/ui/badge";
import { Sparkline } from "@/components/ui/sparkline";
import { Stock } from "@/lib/data";
import { useApi } from "@/lib/use-api";
import { useLivePrices, withLivePrices } from "@/lib/use-live-prices";
import { POLL } from "@/lib/poll";
import { useSparklines } from "@/lib/use-sparklines";
import { useEnsureFresh } from "@/lib/use-fresh";
import { inr, num, mcap, changeText, trendClass } from "@/lib/format";
import { useUI } from "@/components/layout/ui-store";
import { cn } from "@/lib/utils";

function StocksScreener() {
  const { changeMode } = useUI();
  const router = useRouter();
  const sp = useSearchParams();
  const [q, setQ] = useState("");
  const [seg, setSeg] = useState("all");
  // Sector arrives in the URL so the Markets heatmap can deep-link into a
  // pre-filtered screener, and so the filtered view is shareable/bookmarkable.
  const sector = sp.get("sector");
  const universeRaw = useApi<Stock[]>("/api/universe", [], (j) => j.items, POLL.universe);
  // Ticks only for what is on screen — the universe is thousands of rows.
  const live = useLivePrices(universeRaw.slice(0, 120).map((s) => s.symbol));
  const universe = withLivePrices(universeRaw, live);

  const rows = universe.filter((s) => {
    if (sector && s.sector !== sector) return false;
    if (q && !(`${s.symbol} ${s.name}`.toLowerCase().includes(q.toLowerCase()))) return false;
    if (seg === "watch") return s.aiRating === "WATCH";
    if (seg === "gainers") return (s.changePct ?? 0) > 0;
    if (seg === "losers") return (s.changePct ?? 0) < 0;
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

  // Only fetch history for the rows actually on screen.
  const visible = rows.slice(0, 100).map((s) => s.symbol);
  const spark = useSparklines(visible);
  // Ingest-on-view: refresh whatever the user is actually looking at.
  useEnsureFresh(visible);

  const columns: Column<Stock>[] = [
    { key: "symbol", header: "Company", width: "220px", sortable: true, sortValue: (s) => s.symbol,
      cell: (s) => <span className="flex items-center gap-2.5"><Avatar symbol={s.symbol} size={30} /><span className="min-w-0"><span className="block font-semibold text-frost leading-tight">{s.symbol}</span><span className="block text-[11px] text-muted truncate max-w-[140px]">{s.name}</span></span></span> },
    { key: "sector", header: "Sector", cell: (s) => <span className="text-mist text-[12px]">{s.sector}</span> },
    { key: "price", header: "Price", align: "right", sortable: true, sortValue: (s) => s.price, cell: (s) => <span className="tnum font-medium">{inr(s.price)}</span> },
    { key: "chg", header: "Chg%", align: "right", sortable: true, sortValue: (s) => s.changePct, cell: (s) => <span className={cn("tnum font-semibold", trendClass(s.changePct))}>{changeText(s.changePct, s.change, changeMode)}</span> },
    { key: "spark", header: "30D", align: "right", cell: (s) => {
        const d = spark[s.symbol];
        // Real closes, or a dash — never a generated shape.
        return d && d.length > 1
          ? <span className="inline-block"><Sparkline data={d} positive={d[d.length - 1] >= d[0]} width={80} height={24} /></span>
          : <span className="text-faint">—</span>;
      } },
    { key: "mcap", header: "Mkt Cap", align: "right", sortable: true, sortValue: (s) => s.mcapCr, cell: (s) => <span className="tnum text-mist">{mcap(s.mcapCr)}</span> },
    { key: "pe", header: "P/E", align: "right", sortable: true, sortValue: (s) => s.pe, cell: (s) => <span className="tnum text-mist">{num(s.pe)}</span> },
    { key: "roe", header: "ROE", align: "right", sortable: true, sortValue: (s) => s.roe, cell: (s) => <span className="tnum text-mist">{num(s.roe, { suffix: "%" })}</span> },
    { key: "ai", header: "AI Score", align: "right", sortable: true, sortValue: (s) => s.aiScore, cell: (s) => <span className="tnum font-bold text-ai">{num(s.aiScore, { decimals: 1 })}</span> },
    { key: "rating", header: "Rating", align: "right", cell: (s) => <RatingBadge rating={s.aiRating} /> },
  ];

  return (
    <div>
      <PageHeader eyebrow="Trading" title={sector ? `${sector} Stocks` : "Stock Screener"}
        description={sector
          ? `Every ${sector} name in the ARTHA universe — sort, filter, and drill into any of them.`
          : "Institutional-grade data grid across the ARTHA universe — sort, filter, and drill into any name."}
        actions={<Button variant="secondary" size="sm" onClick={exportCsv}><Download size={14} />Export CSV</Button>} />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="flex h-9 items-center gap-2 rounded-[var(--radius-sm)] bg-elevated px-3 hairline w-full sm:w-72">
          <Search size={15} className="text-muted" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter symbols…" className="w-full bg-transparent text-[13px] text-frost outline-none placeholder:text-muted" />
        </div>
        <Segmented value={seg} onChange={setSeg} options={[
          { label: "All", value: "all" }, { label: "On Watch", value: "watch" },
          { label: "Gainers", value: "gainers" }, { label: "Losers", value: "losers" },
        ]} />
        {sector && (
          <button onClick={() => router.push("/stocks")}
            className="flex h-9 items-center gap-1.5 rounded-full bg-accent/15 px-3 text-[12px] font-medium text-accent transition-colors hover:bg-accent/25">
            {sector}<X size={13} />
          </button>
        )}
        <span className="ml-auto text-[12px] text-muted tnum">{rows.length} instruments</span>
      </div>

      <DataGrid columns={columns} rows={rows} rowKey={(s) => s.symbol} onRowClick={(s) => router.push(`/stocks/${s.symbol}`)} />
    </div>
  );
}

// useSearchParams needs a Suspense boundary to keep this page statically
// prerenderable — without it the whole route is forced dynamic.
export default function StocksScreenerPage() {
  return (
    <Suspense fallback={null}>
      <StocksScreener />
    </Suspense>
  );
}
