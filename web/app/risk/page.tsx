"use client";
import { ShieldAlert, TrendingDown, Gauge, Layers, Sparkles } from "lucide-react";
import { PageHeader } from "@/components/widgets/page-header";
import { Card, CardHeader, CardBody } from "@/components/ui/card";
import { Stat, ScoreRing } from "@/components/ui/stat";
import { Badge, AiBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/primitives";
import { Donut, HBars } from "@/components/ui/chart";
import { portfolioSummary, sectorAllocation, RawHolding } from "@/lib/portfolio";
import { Stock } from "@/lib/data";
import { useApi } from "@/lib/use-api";
import { useLivePrices, withLivePrices } from "@/lib/use-live-prices";
import { POLL } from "@/lib/poll";

type RiskMetrics = {
  volatilityAnnualPct?: number; var95Pct?: number; var95Value?: number;
  maxDrawdownPct?: number; observations?: number;
};
import { compactCr, pct } from "@/lib/format";
import { cn } from "@/lib/utils";

const authorize = () => window.dispatchEvent(new Event("artha:authorize"));

export default function Risk() {
  const universeRaw = useApi<Stock[]>("/api/universe", [], (j) => j.items, POLL.universe);
  const holdings = useApi<RawHolding[]>("/api/holdings", [], (j) => j.items ?? [], POLL.holdings);
  const live = useLivePrices(holdings.map((h) => h.symbol));
  const universe = withLivePrices(universeRaw, live);
  const pf = portfolioSummary(holdings, universe);
  const alloc = sectorAllocation(holdings, universe);

  if (!holdings.length) {
    return (
      <div>
        <PageHeader eyebrow="Monitor" title="Risk Analysis"
          description="Portfolio-level risk decomposition over your real positions." actions={<AiBadge>AI Assessed</AiBadge>} />
        <Card><CardBody><EmptyState icon={<ShieldAlert size={22} />} title="No live holdings to assess"
          description="Risk decomposition runs on real Upstox positions only. Re-authorize to load your portfolio."
          action={<Button variant="primary" size="sm" onClick={authorize}>Authorize Upstox</Button>} /></CardBody></Card>
      </div>
    );
  }

  const top = [...pf.rows].sort((a, b) => b.current - a.current)[0];
  const concentration = (top.current / pf.current) * 100;
  // Real risk metrics computed from the portfolio's actual daily value series
  // (holdings x historical closes). Previously beta was the literal constant
  // 1.06, VaR was value x 2.1%, volatility 16.8, Sharpe 1.42 and max drawdown
  // "-14.2%" — every one of them hardcoded, on a page about real money.
  const curveApi = useApi<{ metrics: RiskMetrics; covered: number; total: number }>(
    "/api/portfolio/curve", { metrics: {}, covered: 0, total: 0 }, (j) => j, POLL.curve
  );
  const m = curveApi.metrics ?? {};
  const var95 = m.var95Value ?? null;

  // Composite from real signals only; null when there's no history to judge on.
  const riskScore = (() => {
    if (!m.volatilityAnnualPct && !m.maxDrawdownPct) return null;
    let r = 0;
    r += Math.min(4, concentration / 10);                       // position concentration
    r += Math.min(3, (m.volatilityAnnualPct ?? 0) / 10);        // realised volatility
    r += Math.min(3, Math.abs(m.maxDrawdownPct ?? 0) / 10);     // drawdown depth
    return +Math.min(10, r).toFixed(1);
  })();
  const riskLabel = riskScore == null ? "Not enough history"
    : riskScore >= 7 ? "Elevated" : riskScore >= 4 ? "Moderate" : "Contained";
  const riskSummary = riskScore == null
    ? "Risk needs at least 20 days of portfolio value history to compute."
    : `Top position is ${concentration.toFixed(0)}% of the book`
      + (m.volatilityAnnualPct ? `, realised volatility ${m.volatilityAnnualPct.toFixed(1)}%` : "")
      + (m.maxDrawdownPct ? `, worst drawdown ${m.maxDrawdownPct.toFixed(1)}%` : "") + ".";

  const flags = [
    { name: "Concentration Risk", detail: `${top.symbol} is ${concentration.toFixed(0)}% of book`, sev: concentration > 25 ? "warn" : "pass" },
    { name: "Sector Overexposure", detail: `${alloc[0].name} at ${alloc[0].value.toFixed(0)}%`, sev: alloc[0].value > 40 ? "fail" : alloc[0].value > 30 ? "warn" : "pass" },
    { name: "Volatility", detail: m.volatilityAnnualPct != null ? `${m.volatilityAnnualPct.toFixed(1)}% annualised` : "no history yet",
      sev: (m.volatilityAnnualPct ?? 0) > 30 ? "warn" : "pass" },
    { name: "Drawdown", detail: m.maxDrawdownPct != null ? `Worst peak-to-trough ${m.maxDrawdownPct.toFixed(1)}%` : "no history yet",
      sev: Math.abs(m.maxDrawdownPct ?? 0) > 20 ? "warn" : "pass" },
    { name: "History Coverage", detail: `${curveApi.covered}/${curveApi.total} holdings have price history`,
      sev: curveApi.covered < curveApi.total ? "warn" : "pass" },
  ] as const;
  const tone = { pass: "up", warn: "warn", fail: "down" } as const;

  return (
    <div>
      <PageHeader eyebrow="Monitor" title="Risk Analysis"
        description="Portfolio-level risk decomposition — concentration, factor exposure, VaR, and deterministic flags."
        actions={<AiBadge>AI Assessed</AiBadge>} />

      <div className="mb-6 grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card variant="elevated" className="lg:col-span-2">
          <CardHeader icon={<Gauge size={16} />} title="Risk Metrics"
            subtitle={m.observations ? `Computed from ${m.observations} days of real portfolio value` : "Awaiting price history"} />
          <CardBody className="grid grid-cols-2 gap-6 sm:grid-cols-4">
            <Stat label="Portfolio VaR (95%)" value={var95} prefix="₹" decimals={0} sub="worst 1-day loss, 95% of days" />
            <Stat label="Volatility (ann.)" value={m.volatilityAnnualPct ?? null} decimals={1} suffix="%" sub="realised, annualised" />
            <Stat label="Max Drawdown" value={m.maxDrawdownPct ?? null} decimals={1} suffix="%" sub="peak to trough" />
            <Stat label="Worst Day" value={m.var95Pct ?? null} decimals={2} suffix="%" sub="5th percentile daily return" />
          </CardBody>
        </Card>
        <Card variant="ai">
          <CardHeader icon={<Sparkles size={16} className="text-ai" />} title="Overall Risk" subtitle="AI composite" />
          <CardBody className="flex items-center gap-5">
            <ScoreRing value={riskScore} label="Risk" size={84} />
            <div className="text-[12.5px]">
              <div className="font-semibold text-frost">{riskLabel}</div>
              <p className="mt-1 text-muted">{riskSummary}</p>
            </div>
          </CardBody>
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        <Card>
          <CardHeader icon={<Layers size={16} />} title="Sector Exposure" />
          <CardBody><Donut data={alloc} centerLabel="Sectors" centerValue={`${alloc.length}`} /></CardBody>
        </Card>

        <Card>
          <CardHeader icon={<TrendingDown size={16} />} title="Position Concentration" subtitle="% of portfolio" />
          <CardBody><HBars data={pf.rows.sort((a, b) => b.current - a.current).map((r) => ({ name: r.symbol, value: +((r.current / pf.current) * 100).toFixed(1), color: "var(--color-accent)" }))} height={240} fmt={(v) => `${v}%`} /></CardBody>
        </Card>

        <Card>
          <CardHeader icon={<ShieldAlert size={16} />} title="Risk Flags" subtitle="Deterministic engine" />
          <CardBody className="space-y-2">
            {flags.map((f) => (
              <div key={f.name} className="flex items-center gap-3 rounded-[var(--radius-sm)] bg-void/40 p-3 hairline">
                <span className={cn("h-2 w-2 rounded-full", f.sev === "pass" ? "bg-up" : f.sev === "warn" ? "bg-warn" : "bg-down")} />
                <div className="min-w-0"><div className="text-[12.5px] font-medium text-frost">{f.name}</div><div className="text-[11px] text-muted">{f.detail}</div></div>
                <Badge tone={tone[f.sev]} className="ml-auto">{f.sev}</Badge>
              </div>
            ))}
          </CardBody>
        </Card>
      </div>
    </div>
  );
}
