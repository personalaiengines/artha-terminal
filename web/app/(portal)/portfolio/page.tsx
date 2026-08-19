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
import { portfolioSummary, sectorAllocation, portfolioQuality, RawHolding } from "@/lib/portfolio";
import { series, Stock } from "@/lib/data";
import { useApi } from "@/lib/use-api";
import { useLivePrices, withLivePrices } from "@/lib/use-live-prices";
import { POLL } from "@/lib/poll";
import { useEnsureFresh } from "@/lib/use-fresh";
import { inr, compactCr, trendClass, signed } from "@/lib/format";
import { cn } from "@/lib/utils";

const authorize = () => window.dispatchEvent(new Event("artha:authorize"));

// Green = healthy, amber = watch, red = concerning. Concentration is inverted
// relative to the others: "High" concentration is a risk, "Low" is healthy,
// whereas "High" quality and "Good" diversification are the desirable ends.
const VERDICT_TONE = (label: string, verdict: string | null | undefined) => {
  if (!verdict) return "bg-muted";
  const good = label === "Concentration" ? "Low" : verdict === "Good" ? "Good" : "High";
  const bad = label === "Concentration" ? "High" : "Low";
  return verdict === good ? "bg-up" : verdict === bad ? "bg-down" : "bg-warn";
};

export default function Portfolio() {
  const router = useRouter();
  const universeRaw = useApi<Stock[]>("/api/universe", [], (j) => j.items, POLL.universe);
  const holdings = useApi<RawHolding[]>("/api/holdings", [], (j) => j.items ?? [], POLL.holdings);
  // Your own book first: every held symbol streams, so P&L moves with the market.
  const live = useLivePrices(holdings.map((h) => h.symbol));
  const universe = withLivePrices(universeRaw, live);
  const pf = portfolioSummary(holdings, universe);
  const alloc = sectorAllocation(holdings, universe);
  const quality = portfolioQuality(holdings, universe);
  useEnsureFresh(holdings.map((h) => h.symbol));
  const [range, setRange] = useState("6M");
  // Real portfolio value history: each holding's qty x that day's actual close.
  // Was series(99, 60, invested) — a random walk seeded with the constant 99,
  // so the "performance" chart was identical for every portfolio and never
  // reflected a single real trade.
  const curveApi = useApi<{ points: { t: string; v: number }[]; metrics: any; covered: number; total: number }>(
    "/api/portfolio/curve", { points: [], metrics: {}, covered: 0, total: 0 }, (j) => j, POLL.curve
  );
  const RANGE_DAYS: Record<string, number> = { "1M": 22, "3M": 66, "6M": 126, "1Y": 252, ALL: 10000 };
  const curve = curveApi.points.slice(-(RANGE_DAYS[range] ?? 126));

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
    { key: "pct", header: "Return", align: "right", sortable: true, sortValue: (r) => r.pnlPct, cell: (r) => <DeltaPill value={r.pnl} pct={r.pnlPct} /> },
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
            {curve.length >= 2 ? (
              <>
                <AreaPrice data={curve} dataKey="v" xKey="t" up={pf.pnl >= 0} height={200} showAxes={false} valueFmt={(v) => "₹" + compactCr(v)} />
                {curveApi.covered < curveApi.total && (
                  <p className="mt-2 text-[11px] text-muted">
                    Curve covers {curveApi.covered} of {curveApi.total} holdings — the rest have no price history yet.
                  </p>
                )}
              </>
            ) : (
              <div className="flex h-[200px] items-center justify-center text-[13px] text-muted">
                No price history for these holdings yet — performance chart unavailable.
              </div>
            )}
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
              <ScoreRing value={pf.health == null ? null : pf.health / 10} size={84} label="Score" />
              <div className="space-y-2 text-[12.5px]">
                {([
                  ["Diversification", quality?.diversification, quality && `${quality.holdingCount} holdings · ${quality.sectorCount} sectors`],
                  ["Concentration", quality?.concentration, quality && `top position ${quality.topWeight.toFixed(0)}%`],
                  ["Quality", quality?.quality, "value-weighted health"],
                ] as const).map(([label, verdict, hint]) => (
                  <div key={label} className="flex items-center gap-2" title={hint || undefined}>
                    <span className={cn("h-2 w-2 rounded-full", VERDICT_TONE(label, verdict))} />
                    <span className="text-muted">{label}</span>
                    <span className="ml-auto font-semibold text-frost">{verdict ?? "—"}</span>
                  </div>
                ))}
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
