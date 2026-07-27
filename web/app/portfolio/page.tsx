"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Wallet, PieChart as PieIcon, Sparkles, ShieldAlert, Activity } from "lucide-react";
import { PageHeader } from "@/components/widgets/page-header";
import { Card, CardHeader, CardBody } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Stat, DeltaPill, ScoreRing, HealthBar } from "@/components/ui/stat";
import { Segmented, Avatar, EmptyState } from "@/components/ui/primitives";
import { AreaPrice, Donut, HBars } from "@/components/ui/chart";
import { DataGrid, Column } from "@/components/ui/data-grid";
import { portfolioSummary, sectorAllocation, RawHolding } from "@/lib/portfolio";
import { series, Stock } from "@/lib/data";
import { useApi } from "@/lib/use-api";
import { inr, compactCr, trendClass, signed } from "@/lib/format";
import { cn } from "@/lib/utils";

const authorize = () => window.dispatchEvent(new Event("artha:authorize"));

export default function Portfolio() {
  const router = useRouter();
  const universe = useApi<Stock[]>("/api/universe", [], (j) => j.items);
  const holdings = useApi<RawHolding[]>("/api/holdings", [], (j) => j.items ?? []);
  const pf = portfolioSummary(holdings, universe);
  const alloc = sectorAllocation(holdings, universe);
  const [range, setRange] = useState("6M");
  const curve = series(99, 60, pf.invested || 1, 0.012).map((v, i) => ({ t: i, v }));

  const header = (
    <PageHeader eyebrow="Wealth" title="Portfolio Analytics"
      description="Your positions, performance attribution, and AI-scored portfolio health."
      actions={<Link href={`/ai-analyst?q=${encodeURIComponent("Review the health and risk of my portfolio")}`}><Button variant="ai" size="sm"><Sparkles size={14} />AI Health Review</Button></Link>} />
  );

  if (!holdings.length) {
    return (
      <div>
        {header}
        <Card><CardBody><EmptyState icon={<Wallet size={22} />} title="No live holdings"
          description="This page shows real Upstox positions only — no sample data. If you hold stocks, the daily holdings token has likely expired; re-authorize to load them."
          action={<Button variant="primary" size="sm" onClick={authorize}>Authorize Upstox</Button>} /></CardBody></Card>
      </div>
    );
  }

  type Row = (typeof pf.rows)[number];
  const columns: Column<Row>[] = [
    { key: "symbol", header: "Holding", width: "200px", cell: (r) => <span className="flex items-center gap-2.5"><Avatar symbol={r.symbol} size={30} /><span><span className="block font-semibold text-frost leading-tight">{r.symbol}</span><span className="block text-[11px] text-muted tnum">{r.qty} @ {inr(r.avg, { decimals: 0 })}</span></span></span> },
    { key: "ltp", header: "LTP", align: "right", sortable: true, sortValue: (r) => r.stock.price, cell: (r) => <span className="tnum">{inr(r.stock.price)}</span> },
    { key: "cur", header: "Value", align: "right", sortable: true, sortValue: (r) => r.current, cell: (r) => <span className="tnum font-medium">₹{compactCr(r.current)}</span> },
    { key: "day", header: "Day P&L", align: "right", sortable: true, sortValue: (r) => r.dayPnl, cell: (r) => <span className={cn("tnum", trendClass(r.dayPnl))}>{signed(r.dayPnl, 0)}</span> },
    { key: "pnl", header: "Overall P&L", align: "right", sortable: true, sortValue: (r) => r.pnl, cell: (r) => <span className={cn("tnum font-medium", trendClass(r.pnl))}>{signed(r.pnl, 0)}</span> },
    { key: "pct", header: "Return", align: "right", sortable: true, sortValue: (r) => r.pnlPct, cell: (r) => <DeltaPill pct={r.pnlPct} /> },
    { key: "health", header: "Health", align: "right", cell: (r) => <span className="inline-flex w-16 items-center gap-2"><HealthBar value={r.stock.health} /></span> },
  ];

  return (
    <div>
      {header}

      {/* Summary */}
      <div className="mb-6 grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card variant="elevated" className="lg:col-span-2">
          <CardHeader icon={<Wallet size={16} />} title="Performance" subtitle="Total portfolio value over time"
            action={<Segmented size="sm" value={range} onChange={setRange} options={["1M", "3M", "6M", "1Y", "ALL"].map((v) => ({ label: v, value: v }))} />} />
          <CardBody>
            <div className="mb-4 grid grid-cols-2 gap-5 sm:grid-cols-4">
              <Stat label="Total Value" value={pf.current} prefix="₹" decimals={0} />
              <Stat label="Invested" value={pf.invested} prefix="₹" decimals={0} />
              <Stat label="Day P&L" value={pf.dayPnl} prefix="₹" decimals={0} delta={pf.dayPnlPct} />
              <Stat label="Overall P&L" value={pf.pnl} prefix="₹" decimals={0} delta={pf.pnlPct} />
            </div>
            <AreaPrice data={curve} dataKey="v" xKey="t" up={pf.pnl >= 0} height={200} showAxes={false} valueFmt={(v) => "₹" + compactCr(v)} />
          </CardBody>
        </Card>

        <Card>
          <CardHeader icon={<PieIcon size={16} />} title="Allocation" subtitle="By sector" />
          <CardBody>
            <Donut data={alloc} centerValue={`₹${compactCr(pf.current)}`} centerLabel="Deployed" />
            <div className="mt-3 space-y-1.5">
              {alloc.slice(0, 5).map((a) => (
                <div key={a.name} className="flex items-center gap-2 text-[12px]"><span className="h-2 w-2 rounded-full" style={{ background: a.color }} /><span className="text-muted">{a.name}</span><span className="ml-auto font-medium text-frost tnum">{a.value.toFixed(1)}%</span></div>
              ))}
            </div>
          </CardBody>
        </Card>
      </div>

      {/* Holdings */}
      <div className="mb-6 grid grid-cols-1 gap-6 xl:grid-cols-3">
        <div className="xl:col-span-2">
          <h3 className="mb-3 flex items-center gap-2 text-[15px] font-semibold text-frost"><Activity size={16} className="text-muted" />Holdings</h3>
          <DataGrid columns={columns} rows={pf.rows} rowKey={(r) => r.symbol} onRowClick={(r) => router.push(`/stocks/${r.symbol}`)} />
        </div>

        <div className="space-y-6">
          <Card variant="ai">
            <CardHeader icon={<Sparkles size={16} className="text-ai" />} title="Portfolio Health" subtitle="AI-weighted across holdings" />
            <CardBody className="flex items-center gap-5">
              <ScoreRing value={pf.health / 10} size={84} label="Score" />
              <div className="space-y-2 text-[12.5px]">
                <div className="flex items-center gap-2"><span className="h-2 w-2 rounded-full bg-up" /><span className="text-muted">Diversification</span><span className="ml-auto font-semibold text-frost">Good</span></div>
                <div className="flex items-center gap-2"><span className="h-2 w-2 rounded-full bg-warn" /><span className="text-muted">Concentration</span><span className="ml-auto font-semibold text-frost">Moderate</span></div>
                <div className="flex items-center gap-2"><span className="h-2 w-2 rounded-full bg-up" /><span className="text-muted">Quality</span><span className="ml-auto font-semibold text-frost">High</span></div>
              </div>
            </CardBody>
          </Card>

          <Card>
            <CardHeader icon={<ShieldAlert size={16} />} title="Attribution" subtitle="Contribution to P&L" />
            <CardBody>
              <HBars data={pf.rows.sort((a, b) => b.pnl - a.pnl).slice(0, 6).map((r) => ({ name: r.symbol, value: Math.round(r.pnl) }))} height={200} fmt={(v) => signed(v, 0)} />
            </CardBody>
          </Card>
        </div>
      </div>
    </div>
  );
}
