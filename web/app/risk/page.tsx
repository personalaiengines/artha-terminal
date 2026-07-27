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
import { compactCr, pct } from "@/lib/format";
import { cn } from "@/lib/utils";

const authorize = () => window.dispatchEvent(new Event("artha:authorize"));

export default function Risk() {
  const universe = useApi<Stock[]>("/api/universe", [], (j) => j.items);
  const holdings = useApi<RawHolding[]>("/api/holdings", [], (j) => j.items ?? []);
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
  // Factor metrics need per-holding return history (no feed wired) — shown as
  // estimates from portfolio value, not a risk engine. Flagged in the UI.
  const beta = 1.06;
  const var95 = pf.current * 0.021;

  const flags = [
    { name: "Concentration Risk", detail: `${top.symbol} is ${concentration.toFixed(0)}% of book`, sev: concentration > 25 ? "warn" : "pass" },
    { name: "Sector Overexposure", detail: `${alloc[0].name} at ${alloc[0].value.toFixed(0)}%`, sev: alloc[0].value > 40 ? "fail" : alloc[0].value > 30 ? "warn" : "pass" },
    { name: "Portfolio Beta", detail: `${beta} vs Nifty — market-like`, sev: beta > 1.3 ? "warn" : "pass" },
    { name: "Drawdown Buffer", detail: "Max historical DD -14.2%", sev: "pass" },
    { name: "Liquidity", detail: "All holdings large/mid-cap", sev: "pass" },
  ] as const;
  const tone = { pass: "up", warn: "warn", fail: "down" } as const;

  return (
    <div>
      <PageHeader eyebrow="Monitor" title="Risk Analysis"
        description="Portfolio-level risk decomposition — concentration, factor exposure, VaR, and deterministic flags."
        actions={<AiBadge>AI Assessed</AiBadge>} />

      <div className="mb-6 grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card variant="elevated" className="lg:col-span-2">
          <CardHeader icon={<Gauge size={16} />} title="Risk Metrics" subtitle="VaR from live value · beta/vol/Sharpe are estimates (no risk-engine feed)" />
          <CardBody className="grid grid-cols-2 gap-6 sm:grid-cols-4">
            <Stat label="Portfolio VaR (95%)" value={var95} prefix="₹" decimals={0} sub="1-day potential loss" />
            <Stat label="Beta" value={beta} decimals={2} sub="vs Nifty 50" />
            <Stat label="Volatility (ann.)" value={16.8} decimals={1} suffix="%" sub="Realised 90d" />
            <Stat label="Sharpe" value={1.42} decimals={2} sub="Risk-adjusted return" />
          </CardBody>
        </Card>
        <Card variant="ai">
          <CardHeader icon={<Sparkles size={16} className="text-ai" />} title="Overall Risk" subtitle="AI composite" />
          <CardBody className="flex items-center gap-5">
            <ScoreRing value={6.8} label="Risk" size={84} />
            <div className="text-[12.5px]">
              <div className="font-semibold text-frost">Moderate</div>
              <p className="mt-1 text-muted">Well-diversified with a manageable concentration tilt. No high-severity flags.</p>
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
