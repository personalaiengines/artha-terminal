"use client";
import { useMemo, useRef, useState } from "react";
import {
  Activity, AlertTriangle, Gauge, Grid3x3, Layers, ShieldAlert, TrendingDown, Waves,
} from "lucide-react";
import {
  Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { PageHeader } from "@/components/widgets/page-header";
import { Card, CardHeader, CardBody } from "@/components/ui/card";
import { Stat, ScoreRing } from "@/components/ui/stat";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/primitives";
import { AreaPrice, Donut, ZeroArea } from "@/components/ui/chart";
import { portfolioSummary, sectorAllocation, RawHolding } from "@/lib/portfolio";
import { Stock } from "@/lib/data";
import { useApi } from "@/lib/use-api";
import { useLivePrices, withLivePrices } from "@/lib/use-live-prices";
import { POLL } from "@/lib/poll";
import { compactCr, inr } from "@/lib/format";
import { cn } from "@/lib/utils";
import {
  beta, correlationMatrix, drawdownStats, hhi, histogram, percentile, returns,
  riskContribution, stressScenarios, type Point,
} from "@/lib/risk";

// Portfolio risk, computed from the book's own 250-day value series and the
// per-symbol close history behind it. Nothing here is modelled or assumed — the
// page's own history is that beta was once the literal constant 1.06 and VaR was
// value x 2.1%, so every figure below either comes out of a real series or
// renders as "—" with the reason stated.
//
// The metrics are also deliberately split by what they can see: volatility and
// VaR describe the book as one number, drawdown describes the path it took, and
// risk contribution describes which position is actually responsible. A
// value-weighted concentration bar answers none of the last one.

type RiskMetrics = {
  volatilityAnnualPct?: number; var95Pct?: number; var95Value?: number;
  maxDrawdownPct?: number; observations?: number;
};

const BENCH = "NIFTY";

const TABS = [
  { id: "overview", label: "Overview", icon: <Activity size={13} /> },
  { id: "drawdown", label: "Drawdown", icon: <Waves size={13} /> },
  { id: "positions", label: "Positions", icon: <Layers size={13} /> },
  { id: "correlation", label: "Correlation", icon: <Grid3x3 size={13} /> },
] as const;
type Tab = (typeof TABS)[number]["id"];

const authorize = () => window.dispatchEvent(new Event("artha:authorize"));

const signedPct = (n: number | null | undefined, dp = 1) =>
  typeof n === "number" && Number.isFinite(n)
    ? `${n > 0 ? "+" : n < 0 ? "−" : ""}${Math.abs(n).toFixed(dp)}%`
    : "—";

const dayLabel = (iso: string) =>
  new Date(iso + "T00:00:00").toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "2-digit" });

/** One line under a figure saying how it was computed and over what window.
 *  A risk number whose definition and sample are invisible cannot be acted on. */
function Method({ children }: { children: React.ReactNode }) {
  return <p className="mt-1.5 text-[10.5px] leading-snug text-faint">{children}</p>;
}

function Panel({ title, subtitle, icon, children, className }: {
  title: string; subtitle?: string; icon?: React.ReactNode;
  children: React.ReactNode; className?: string;
}) {
  return (
    <Card className={className}>
      <CardHeader icon={icon} title={title} subtitle={subtitle} />
      <CardBody className="pt-0">{children}</CardBody>
    </Card>
  );
}

function TooltipBox({ children }: { children: React.ReactNode }) {
  return (
    <div className="glass rounded-[var(--radius-sm)] px-3 py-2 text-[12px] shadow-[var(--shadow-lg)] hairline">{children}</div>
  );
}

export default function Risk() {
  // ---- every hook runs on every render ------------------------------------
  // This page previously called one of these AFTER the early return below, so
  // the first render (holdings still the empty fallback) ran fewer hooks than
  // the next one and React threw "Rendered more hooks than during the previous
  // render". It only looked fine for an account with nothing to show.
  const universeRaw = useApi<Stock[]>("/api/universe", [], (j) => j.items, POLL.universe);
  const holdings = useApi<RawHolding[]>("/api/holdings", [], (j) => j.items ?? [], POLL.holdings);
  const live = useLivePrices(holdings.map((h) => h.symbol));
  const curveApi = useApi<{ points: Point[]; metrics: RiskMetrics; covered: number; total: number }>(
    "/api/portfolio/curve", { points: [], metrics: {}, covered: 0, total: 0 }, (j) => j, POLL.curve
  );

  const symbolKey = holdings.map((h) => h.symbol).sort().join(",");
  const hist = useApi<Record<string, number[]>>(
    `/api/history?symbols=${symbolKey ? symbolKey + "," : ""}${BENCH}&days=250`,
    {}, (j) => j.series ?? {}, POLL.history
  );

  const [tab, setTab] = useState<Tab>("overview");
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);

  const universe = withLivePrices(universeRaw, live);
  const pf = portfolioSummary(holdings, universe);
  const alloc = sectorAllocation(holdings, universe);

  const points = curveApi.points ?? [];
  const m = curveApi.metrics ?? {};

  const dd = useMemo(() => drawdownStats(points), [points]);
  const portfolioReturns = useMemo(() => returns(points.map((p) => p.v)), [points]);
  const bins = useMemo(() => histogram(portfolioReturns.map((r) => r * 100), 25), [portfolioReturns]);

  const localVar95 = useMemo(() => percentile(portfolioReturns, 0.05), [portfolioReturns]);

  // Keyed off a value string, not `pf.rows`. `portfolioSummary` builds a new
  // array every render and `useLivePrices` re-renders on every websocket tick,
  // so a `[pf.rows]` dependency rebuilt the whole 6x6 covariance matrix over
  // 249 returns many times a second during market hours — and handed the
  // Positions tab a new object identity each time, re-animating it.
  //
  // Keyed on each position's share of the book in permille, not on its rupee
  // value: `current` is qty x price, so for any holding of ~20 shares a single
  // 5-paisa tick moves it past a whole rupee and a rounded-rupee key would flip
  // on essentially every tick. The maths only consumes relative weights, so this
  // is also correctly invariant to the whole book drifting together.
  const weightKey = pf.current > 0
    ? pf.rows.map((r) => `${r.symbol}:${Math.round((r.current / pf.current) * 1000)}`).join("|")
    : pf.rows.map((r) => r.symbol).join("|");
  const weights = useMemo(
    () => Object.fromEntries(pf.rows.map((r) => [r.symbol, r.current])),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [weightKey]
  );
  const contrib = useMemo(() => riskContribution(weights, hist), [weights, hist]);
  const corr = useMemo(
    () => correlationMatrix(Object.fromEntries(
      Object.entries(hist).filter(([s]) => s !== BENCH)
    )),
    [hist]
  );
  const portfolioBeta = useMemo(() => {
    const b = hist[BENCH];
    return b?.length ? beta(portfolioReturns, returns(b)) : null;
  }, [portfolioReturns, hist]);

  const onTabKey = (e: React.KeyboardEvent<HTMLButtonElement>, i: number) => {
    const n = e.key === "ArrowRight" ? (i + 1) % TABS.length
      : e.key === "ArrowLeft" ? (i - 1 + TABS.length) % TABS.length
        : e.key === "Home" ? 0 : e.key === "End" ? TABS.length - 1 : -1;
    if (n < 0) return;
    e.preventDefault();
    setTab(TABS[n].id);
    tabRefs.current[n]?.focus();
  };

  if (!holdings.length) {
    return (
      <div>
        <PageHeader eyebrow="Monitor" title="Risk Analysis"
          description="Portfolio-level risk decomposition over your real positions."
          actions={<Badge tone="neutral">Computed, not modelled</Badge>} />
        <Card><CardBody><EmptyState icon={<ShieldAlert size={22} />} title="No live holdings to assess"
          description="Risk decomposition runs on real Upstox positions only. Re-authorize to load your portfolio."
          action={<Button variant="primary" size="sm" onClick={authorize}>Authorize Upstox</Button>} /></CardBody></Card>
      </div>
    );
  }

  // ---- derived read-outs ---------------------------------------------------
  const top = [...pf.rows].sort((a, b) => b.current - a.current)[0];
  // An unpriced book totals zero, and x/0 printed "NaN% of book" on a risk page.
  const concentration = top && pf.current > 0 ? (top.current / pf.current) * 100 : null;
  const topSector = alloc[0] ?? null;
  const conc = hhi(pf.rows.map((r) => r.current));
  const scenarios = stressScenarios(pf.current, portfolioReturns);
  const positiveDays = portfolioReturns.length
    ? (portfolioReturns.filter((r) => r > 0).length / portfolioReturns.length) * 100 : null;

  const riskScore = (() => {
    if (concentration == null) return null;
    if (!m.volatilityAnnualPct && !m.maxDrawdownPct) return null;
    let r = 0;
    r += Math.min(4, concentration / 10);
    r += Math.min(3, (m.volatilityAnnualPct ?? 0) / 10);
    r += Math.min(3, Math.abs(m.maxDrawdownPct ?? 0) / 10);
    return +Math.min(10, r).toFixed(1);
  })();
  const riskLabel = riskScore == null ? "Not enough history"
    : riskScore >= 7 ? "Elevated" : riskScore >= 4 ? "Moderate" : "Contained";

  // The single position whose share of risk most exceeds its share of money —
  // the thing this page exists to surface and a weight chart cannot show.
  const riskOutlier = [...contrib.rows]
    .filter((r) => r.riskPct != null)
    .sort((a, b) => (b.riskPct! - b.weightPct) - (a.riskPct! - a.weightPct))[0];

  // "na" is not "pass". A flag that reads green because its input was missing is
  // the worst failure mode on a risk page.
  const flags = [
    { name: "Concentration", detail: concentration == null ? "no valuation yet" : `${top.symbol} is ${concentration.toFixed(0)}% of book`,
      sev: concentration == null ? "na" : concentration > 25 ? "warn" : "pass" },
    { name: "Sector exposure", detail: topSector ? `${topSector.name} at ${topSector.value.toFixed(0)}%` : "no sector breakdown yet",
      sev: !topSector ? "na" : topSector.value > 40 ? "fail" : topSector.value > 30 ? "warn" : "pass" },
    { name: "Volatility", detail: m.volatilityAnnualPct != null ? `${m.volatilityAnnualPct.toFixed(1)}% annualised` : "no history yet",
      sev: m.volatilityAnnualPct == null ? "na" : m.volatilityAnnualPct > 30 ? "warn" : "pass" },
    { name: "Drawdown", detail: m.maxDrawdownPct != null ? `worst peak-to-trough ${m.maxDrawdownPct.toFixed(1)}%` : "no history yet",
      sev: m.maxDrawdownPct == null ? "na" : Math.abs(m.maxDrawdownPct) > 20 ? "warn" : "pass" },
    { name: "Risk vs weight", detail: riskOutlier
        ? `${riskOutlier.symbol} carries ${riskOutlier.riskPct!.toFixed(0)}% of risk on ${riskOutlier.weightPct.toFixed(0)}% of money`
        : "needs overlapping price history",
      sev: !riskOutlier ? "na" : riskOutlier.riskPct! - riskOutlier.weightPct > 15 ? "warn" : "pass" },
    { name: "History coverage", detail: curveApi.total ? `${curveApi.covered}/${curveApi.total} holdings priced` : "awaiting price history",
      sev: !curveApi.total ? "na" : curveApi.covered < curveApi.total ? "warn" : "pass" },
  ] as const;
  const tone = { pass: "up", warn: "warn", fail: "down", na: "neutral" } as const;
  const dot = { pass: "bg-up", warn: "bg-warn", fail: "bg-down", na: "bg-faint" } as const;

  // Written out rather than chained: `??` binds looser than `!==`, so the
  // compact one-liner this replaced used the *value* as the ternary condition
  // and turned a legitimate 0.00% VaR into "unknown". It also sorted 249
  // returns twice on every render.
  const var95Pct = m.var95Pct ?? (localVar95 == null ? null : localVar95 * 100);

  return (
    <div>
      <PageHeader eyebrow="Monitor" title="Risk Analysis"
        description="What this book is actually exposed to — measured from its own value history, not modelled."
        actions={<Badge tone="neutral">Computed, not modelled</Badge>} />

      {/* ---- KPI strip, pinned under the h-14 topbar ---- */}
      <div className="sticky top-14 z-20 mb-6 grid grid-cols-2 gap-3 rounded-[var(--radius-lg)] bg-elevated/92 p-3 backdrop-blur-xl hairline-strong md:grid-cols-3 xl:grid-cols-6">
        <Stat label="Value at Risk (95%)" value={m.var95Value ?? null} prefix="₹" decimals={0}
          sub={var95Pct != null ? `${var95Pct.toFixed(2)}% of book` : "1-day"} />
        <Stat label="Volatility" value={m.volatilityAnnualPct ?? null} decimals={1} suffix="%" sub="annualised" />
        <Stat label="Max drawdown" value={m.maxDrawdownPct ?? null} decimals={1} suffix="%" sub="peak to trough" />
        <Stat label={`Beta vs ${BENCH}`} value={portfolioBeta} decimals={2}
          sub={portfolioBeta == null ? "no benchmark history" : portfolioBeta > 1 ? "moves more than the index" : "moves less than the index"} />
        <Stat label="Concentration" value={conc} decimals={0}
          sub={conc == null ? "—" : conc > 2500 ? "HHI · concentrated" : "HHI · spread"} />
        <div className="flex items-center gap-3">
          {/* tone="risk" inverts the band — on this scale high is bad. */}
          <ScoreRing value={riskScore} label="Risk" size={54} tone="risk" />
          <div className="min-w-0">
            <div className="text-[10.5px] font-medium uppercase tracking-wide text-muted">Composite</div>
            <div className="truncate text-[13px] font-semibold text-frost">{riskLabel}</div>
          </div>
        </div>
      </div>

      {/* R6 for the strip: the figures above are the most prominent on the page,
          so what they are and where they come from is stated, not assumed. */}
      <details className="mb-6 rounded-[var(--radius-md)] bg-void/40 px-3.5 py-2.5 hairline">
        <summary className="ring-focus cursor-pointer text-[11.5px] font-medium text-muted transition-colors hover:text-mist">
          How these six figures are computed
        </summary>
        <dl className="mt-2.5 grid gap-x-6 gap-y-2 text-[11px] leading-snug sm:grid-cols-2">
          {([
            ["Value at Risk (95%)", `5th percentile of ${m.observations ?? portfolioReturns.length} daily portfolio returns. One session in twenty was worse than this. A loss size, not a worst case — nothing bounds the other 5%.`],
            ["Volatility", "Standard deviation of daily portfolio returns × √252. Describes the whole book as one number and says nothing about which position causes it — see the Positions tab."],
            ["Max drawdown", "Largest peak-to-trough fall of the portfolio value series, measured against the running peak up to each day."],
            [`Beta vs ${BENCH}`, `cov(portfolio, ${BENCH}) ÷ var(${BENCH}) over the overlapping daily returns. 1.0 means it has moved one-for-one with the index.`],
            ["Concentration (HHI)", "Sum of squared percentage weights. One position scores 10,000; n equal positions score 10,000/n. Above ~2,500 is conventionally 'concentrated'."],
            ["Composite risk", "A fixed in-house 0–10 blend, NOT an industry measure: min(4, concentration/10) + min(3, volatility/10) + min(3, |drawdown|/10). The coefficients and caps are chosen, not derived — treat it as a summary of the three figures above it, not a new measurement."],
          ] as const).map(([k, v]) => (
            <div key={k}>
              <dt className="font-medium text-mist">{k}</dt>
              <dd className="mt-0.5 text-faint">{v}</dd>
            </div>
          ))}
        </dl>
      </details>

      {/* ---- tabs ---- */}
      <div role="tablist" aria-label="Risk views" className="mb-5 flex items-center gap-1 border-b border-line">
        {TABS.map((t, i) => (
          <button key={t.id} type="button" role="tab" id={`risk-tab-${t.id}`}
            aria-selected={tab === t.id} aria-controls={`risk-panel-${t.id}`}
            tabIndex={tab === t.id ? 0 : -1}
            ref={(el) => { tabRefs.current[i] = el; }}
            onKeyDown={(e) => onTabKey(e, i)} onClick={() => setTab(t.id)}
            className={cn(
              "ring-focus relative flex cursor-pointer items-center gap-1.5 px-3.5 py-2 text-[12.5px] font-medium transition-colors duration-150",
              tab === t.id ? "text-frost" : "text-muted hover:text-mist"
            )}>
            {t.icon}{t.label}
            {tab === t.id && <span className="absolute inset-x-0 -bottom-px h-0.5 rounded-full bg-accent" />}
          </button>
        ))}
      </div>

      <div key={tab} role="tabpanel" id={`risk-panel-${tab}`} aria-labelledby={`risk-tab-${tab}`} className="rise">

        {tab === "overview" && (
          <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
            <Panel className="xl:col-span-2" icon={<Activity size={16} />} title="Portfolio value"
              subtitle={points.length ? `${points.length} sessions · ${dayLabel(points[0].t)} → ${dayLabel(points[points.length - 1].t)}` : "awaiting history"}>
              {points.length > 1 ? (
                <>
                  <AreaPrice data={points as unknown as Record<string, unknown>[]} dataKey="v" xKey="t" height={260}
                    up={points[points.length - 1].v >= points[0].v}
                    valueFmt={(v) => "₹" + compactCr(v)} />
                  <Method>
                    Each day&apos;s holdings valued at that day&apos;s closes — the same series every statistic on this
                    page is computed from. {curveApi.covered}/{curveApi.total} holdings have price history;
                    any without one contribute nothing rather than a zero.
                  </Method>
                </>
              ) : <p className="py-16 text-center text-[12.5px] text-muted">No portfolio value history yet.</p>}
            </Panel>

            <Panel icon={<ShieldAlert size={16} />} title="Risk flags" subtitle="Deterministic checks">
              <div className="space-y-2">
                {flags.map((f) => (
                  <div key={f.name} className="flex items-center gap-3 rounded-[var(--radius-sm)] bg-void/40 p-2.5 hairline">
                    <span className={cn("h-2 w-2 shrink-0 rounded-full", dot[f.sev])} />
                    <div className="min-w-0">
                      <div className="text-[12px] font-medium text-frost">{f.name}</div>
                      <div className="text-[11px] leading-snug text-muted">{f.detail}</div>
                    </div>
                    <Badge tone={tone[f.sev]} className="ml-auto shrink-0">{f.sev}</Badge>
                  </div>
                ))}
              </div>
              <Method>
                Fixed thresholds, no model. <span className="text-muted">na</span> means the input was missing —
                it is not a pass.
              </Method>
            </Panel>

            <Panel className="xl:col-span-3" icon={<AlertTriangle size={16} />} title="Stress scenarios"
              subtitle="What a one-day shock costs this book">
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                {scenarios.map((s) => (
                  <div key={s.label} className="rounded-[var(--radius-md)] bg-void p-3.5 hairline">
                    <div className="flex items-center gap-1.5">
                      <span className="text-[11px] font-medium text-mist">{s.label}</span>
                      {s.observed
                        ? <Badge tone="neutral">observed</Badge>
                        : <Badge tone="warn">hypothetical</Badge>}
                    </div>
                    <div className="mt-1.5 text-[20px] font-semibold leading-none tracking-tight text-down tnum">
                      −{inr(Math.abs(s.value), { decimals: 0 })}
                    </div>
                    <div className="mt-1 text-[11px] text-faint tnum">{signedPct(s.pct, 2)} of ₹{compactCr(pf.current)}</div>
                    <div className="mt-1 text-[10.5px] leading-snug text-faint">{s.note}</div>
                  </div>
                ))}
              </div>
              <Method>
                Applied to the book&apos;s current value. &ldquo;Observed&rdquo; shocks are days this portfolio actually
                lived through; &ldquo;hypothetical&rdquo; are round numbers and have never happened — the distinction is
                marked because presenting one as the other is how a stress test misleads.
              </Method>
            </Panel>
          </div>
        )}

        {tab === "drawdown" && (
          <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
            <Panel className="xl:col-span-3" icon={<Waves size={16} />} title="Underwater"
              subtitle="Percent below the running peak, every session">
              {dd.series.length > 1 ? (
                <>
                  <ZeroArea data={dd.series.map((d) => ({ t: d.t, v: d.ddPct }))} height={260}
                    color="var(--color-down)" label="Drawdown"
                    valueFmt={(v) => `${v.toFixed(1)}%`} />
                  <div className="mt-3 grid gap-3 sm:grid-cols-4">
                    <div className="rounded-[var(--radius-md)] bg-void p-3 hairline">
                      <div className="text-[10px] uppercase tracking-wide text-muted">Deepest</div>
                      <div className="mt-1 text-[18px] font-semibold text-down tnum">{signedPct(dd.worstPct)}</div>
                      <div className="mt-0.5 text-[10.5px] text-faint">{dd.worstAt ? dayLabel(dd.worstAt) : "—"}</div>
                    </div>
                    <div className="rounded-[var(--radius-md)] bg-void p-3 hairline">
                      <div className="text-[10px] uppercase tracking-wide text-muted">Longest underwater</div>
                      <div className="mt-1 text-[18px] font-semibold text-frost tnum">{dd.longestDays}</div>
                      <div className="mt-0.5 text-[10.5px] text-faint">consecutive sessions below a prior peak</div>
                    </div>
                    <div className="rounded-[var(--radius-md)] bg-void p-3 hairline">
                      <div className="text-[10px] uppercase tracking-wide text-muted">Right now</div>
                      <div className={cn("mt-1 text-[18px] font-semibold tnum", dd.recovered ? "text-up" : "text-down")}>
                        {dd.recovered ? "At peak" : signedPct(dd.currentPct)}
                      </div>
                      <div className="mt-0.5 text-[10.5px] text-faint">{dd.recovered ? "fully recovered" : "below the high-water mark"}</div>
                    </div>
                    <div className="rounded-[var(--radius-md)] bg-void p-3 hairline">
                      <div className="text-[10px] uppercase tracking-wide text-muted">Positive days</div>
                      <div className="mt-1 text-[18px] font-semibold text-frost tnum">
                        {positiveDays == null ? "—" : `${positiveDays.toFixed(0)}%`}
                      </div>
                      <div className="mt-0.5 text-[10.5px] text-faint">of {portfolioReturns.length} sessions</div>
                    </div>
                  </div>
                  <Method>
                    Drawdown is measured against the highest value reached <em>up to that day</em>, never a later
                    peak. Depth alone understates a drawdown — how long the book stayed under water is what decides
                    whether it was survivable.
                  </Method>
                </>
              ) : <p className="py-16 text-center text-[12.5px] text-muted">Not enough history to plot a drawdown.</p>}
            </Panel>

            <Panel className="xl:col-span-3" icon={<TrendingDown size={16} />} title="Daily return distribution"
              subtitle={`${portfolioReturns.length} sessions, with the VaR threshold marked`}>
              {bins.length ? (
                <>
                  <ResponsiveContainer width="100%" height={240}>
                    <BarChart data={bins} margin={{ top: 8, right: 6, left: 0, bottom: 0 }}>
                      <CartesianGrid stroke="var(--color-line)" vertical={false} opacity={0.4} />
                      <XAxis dataKey="mid" stroke="var(--color-faint)" fontSize={10} tickLine={false} axisLine={false}
                        tickFormatter={(v) => `${Number(v).toFixed(1)}%`} minTickGap={28} />
                      <YAxis stroke="var(--color-faint)" fontSize={10} tickLine={false} axisLine={false}
                        width={34} orientation="right" allowDecimals={false} />
                      {var95Pct != null && (
                        <ReferenceLine x={bins.reduce((best, b) =>
                          Math.abs(b.mid - var95Pct) < Math.abs(best - var95Pct) ? b.mid : best, bins[0].mid)}
                          stroke="var(--color-warn)" strokeDasharray="4 3" />
                      )}
                      <Tooltip cursor={{ fill: "var(--color-raised)", opacity: 0.3 }}
                        content={({ active, payload }) => {
                          const b = active && payload?.length ? (payload[0].payload as (typeof bins)[number]) : null;
                          return b ? (
                            <TooltipBox>
                              <div className="text-muted">{b.lo.toFixed(2)}% to {b.hi.toFixed(2)}%</div>
                              <div className="font-semibold text-frost tnum">{b.count} session{b.count === 1 ? "" : "s"}</div>
                            </TooltipBox>
                          ) : null;
                        }} />
                      <Bar dataKey="count" maxBarSize={26} radius={[3, 3, 0, 0]}>
                        {bins.map((b, i) => (
                          <Cell key={i} fill={b.mid < 0 ? "var(--color-down)" : "var(--color-up)"} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                  <Method>
                    Each bar counts the sessions whose return fell in that range, over {portfolioReturns.length}{" "}
                    sessions in {bins.length} equal-width bins. Losing days sit left of zero on the axis — the
                    sign is carried by position and by the printed axis labels, not by the bar colour alone.
                    The dashed line marks the 5th percentile
                    ({var95Pct != null ? `${var95Pct.toFixed(2)}%` : "—"}), the VaR threshold: 95% of observed
                    days were better, which also means one day in twenty was worse. It is drawn at the nearest
                    bin centre — up to half a bin (~{bins.length ? ((bins[0].hi - bins[0].lo) / 2).toFixed(2) : "0"}%)
                    from the exact figure quoted here, because the axis is categorical.
                  </Method>
                </>
              ) : <p className="py-16 text-center text-[12.5px] text-muted">Not enough sessions to bin.</p>}
            </Panel>
          </div>
        )}

        {tab === "positions" && (
          <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
            <Panel className="xl:col-span-2" icon={<Gauge size={16} />} title="Risk contribution"
              subtitle="Share of portfolio volatility against share of money">
              {contrib.rows.length ? (
                <>
                  <div className="space-y-2.5">
                    {[...contrib.rows]
                      .sort((a, b) => (b.riskPct ?? b.weightPct) - (a.riskPct ?? a.weightPct))
                      .map((r) => {
                        const gap = r.riskPct == null ? null : r.riskPct - r.weightPct;
                        return (
                          <div key={r.symbol} className="rounded-[var(--radius-sm)] bg-void/50 p-2.5 hairline">
                            <div className="flex items-baseline gap-2">
                              <span className="text-[12.5px] font-semibold text-frost">{r.symbol}</span>
                              {gap != null && Math.abs(gap) >= 5 && (
                                <Badge tone={gap > 0 ? "warn" : "neutral"}>
                                  {gap > 0 ? "riskier than its weight" : "safer than its weight"}
                                </Badge>
                              )}
                              <span className="ml-auto text-[11px] text-faint tnum">
                                {r.volPct == null ? "—" : `${r.volPct.toFixed(0)}% vol`}
                              </span>
                            </div>
                            {/* Two bars, same scale: money on top, risk beneath. */}
                            {([["Money", r.weightPct, "bg-accent"], ["Risk", r.riskPct, "bg-warn"]] as const).map(
                              ([label, val, color]) => (
                                <div key={label} className="mt-1.5 flex items-center gap-2">
                                  <span className="w-10 shrink-0 text-[10px] uppercase tracking-wide text-faint">{label}</span>
                                  <div className="h-2 flex-1 overflow-hidden rounded-full bg-line">
                                    {val != null && <div className={cn("h-full rounded-full", color)} style={{ width: `${Math.min(100, val)}%` }} />}
                                  </div>
                                  <span className="w-11 shrink-0 text-right text-[11px] text-mist tnum">
                                    {val == null ? "—" : `${val.toFixed(1)}%`}
                                  </span>
                                </div>
                              )
                            )}
                          </div>
                        );
                      })}
                  </div>
                  <Method>
                    Risk share is σᵢ&apos;s component of portfolio volatility (wᵢ·(Σw)ᵢ ⁄ σ²ₚ), so the column sums to
                    100%. It is not the same as the money column: a small position in a volatile name that moves
                    with the rest of the book can carry far more risk than its weight suggests — which is exactly
                    what a weight chart cannot show.
                    {contrib.portfolioVolPct != null && (
                      <> Volatility implied by today&apos;s weights held constant across the window:{" "}
                        {contrib.portfolioVolPct.toFixed(1)}% annualised. That is deliberately a different number
                        from the {m.volatilityAnnualPct != null ? `${m.volatilityAnnualPct.toFixed(1)}% ` : ""}
                        headline above, which measures the book as it was actually held, with every trade in it.</>
                    )}
                    {contrib.rows.some((r) => r.riskPct == null) && " Rows without a risk share lack overlapping price history."}
                    {" "}Symbols are paired by position on their most recent sessions; the price API returns no
                    dates, so a suspended session for one name would misalign it.
                  </Method>
                </>
              ) : <p className="py-16 text-center text-[12.5px] text-muted">No positions to decompose.</p>}
            </Panel>

            <Panel icon={<Layers size={16} />} title="Sector exposure">
              {alloc.length ? (
                <>
                  <Donut data={alloc} centerLabel="Sectors" centerValue={`${alloc.length}`} />
                  <Method>
                    Share of current market value by the sector each holding is mapped to. Sector spread is not
                    the same as diversification — see the Correlation tab for whether they actually move apart.
                  </Method>
                </>
              ) : <p className="py-14 text-center text-[12.5px] text-muted">No sector breakdown until the book is priced.</p>}
            </Panel>
          </div>
        )}

        {tab === "correlation" && (
          <Panel icon={<Grid3x3 size={16} />} title="Correlation matrix"
            subtitle={`Daily-return correlation · ${corr.symbols.length} of ${holdings.length} holdings have usable history`}>
            {corr.symbols.length > 1 ? (
              <>
                <div className="overflow-x-auto scrollbar-slim">
                  <table className="text-[11px] tnum">
                    <thead>
                      <tr>
                        <th className="sticky left-0 bg-elevated p-1.5" />
                        {corr.symbols.map((s) => (
                          <th key={s} className="p-1.5 text-[10px] font-medium text-muted">
                            <span className="block max-w-[64px] truncate">{s}</span>
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {corr.symbols.map((rowSym, i) => (
                        <tr key={rowSym}>
                          <th className="sticky left-0 bg-elevated p-1.5 text-right text-[10px] font-medium text-muted">
                            <span className="block max-w-[76px] truncate">{rowSym}</span>
                          </th>
                          {corr.symbols.map((colSym, j) => {
                            const v = corr.matrix[i][j];
                            // Intensity carries magnitude, hue carries sign, and
                            // the number is always printed — colour alone never
                            // has to be read.
                            const a = v == null ? 0 : Math.min(1, Math.abs(v));
                            const bg = v == null ? "transparent"
                              : v >= 0
                                ? `color-mix(in oklab, var(--color-down) ${Math.round(a * 62)}%, transparent)`
                                : `color-mix(in oklab, var(--color-accent) ${Math.round(a * 62)}%, transparent)`;
                            return (
                              <td key={colSym} className="p-0.5">
                                <div className="flex h-9 min-w-[52px] items-center justify-center rounded-[var(--radius-xs)] hairline"
                                  style={{ background: bg }}
                                  title={`${rowSym} vs ${colSym}: ${v == null ? "no overlapping history" : v.toFixed(2)}`}>
                                  <span className={cn(a > 0.55 ? "text-frost" : "text-mist")}>
                                    {v == null ? "—" : v.toFixed(2)}
                                  </span>
                                </div>
                              </td>
                            );
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <div className="mt-3 flex flex-wrap items-center gap-4 text-[10.5px] text-faint">
                  <span className="flex items-center gap-1.5">
                    <span className="h-2.5 w-2.5 rounded-[3px]" style={{ background: "color-mix(in oklab, var(--color-down) 62%, transparent)" }} />
                    move together (+1) — less diversification than the count suggests
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className="h-2.5 w-2.5 rounded-[3px]" style={{ background: "color-mix(in oklab, var(--color-accent) 62%, transparent)" }} />
                    move apart (−1) — one offsets the other
                  </span>
                </div>
                <Method>
                  Pearson correlation of daily returns over the overlapping history of each pair. Red here does not
                  mean &ldquo;losing&rdquo; — it means the two names move as one, which is the risk a sector
                  breakdown cannot see. Holding several names that all sit near +1 is closer to holding one
                  position than the position count implies.
                  {corr.symbols.length < holdings.length &&
                    ` ${holdings.length - corr.symbols.length} holding(s) are absent for want of price history — the grid is not the whole book.`}
                  {" "}Pairs are aligned on their most recent sessions by position: the price API returns each
                  symbol&apos;s own last 250 closes without dates, so a symbol suspended for a session would shift
                  against the others. Correcting that needs dates on the history endpoint.
                </Method>
              </>
            ) : (
              <p className="py-16 text-center text-[12.5px] text-muted">
                Need at least two holdings with overlapping price history to correlate.
              </p>
            )}
          </Panel>
        )}
      </div>
    </div>
  );
}
