"use client";
import Link from "next/link";
import { ArrowRight, Sparkles, TrendingUp, TrendingDown, CalendarClock, Newspaper, Wallet, FlaskConical } from "lucide-react";
import { PageHeader } from "@/components/widgets/page-header";
import { Card, CardHeader, CardBody } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { AiBadge, RatingBadge, ImpactBadge } from "@/components/ui/badge";
import { Stat, DeltaPill, ScoreRing } from "@/components/ui/stat";
import { Sparkline } from "@/components/ui/sparkline";
import { LiveDot } from "@/components/ui/primitives";
import { StockRow } from "@/components/widgets/stock-row";
import { NewsCard } from "@/components/widgets/news-card";
import { series, Stock, NewsItem, EconEvent } from "@/lib/data";
import { moversFrom, portfolioSummary, RawHolding } from "@/lib/portfolio";
import { useApi } from "@/lib/use-api";
import { pct, trendClass } from "@/lib/format";
import { cn } from "@/lib/utils";

type GlobalRow = { name: string; price: number | null; changePct: number | null };
type Pulse = { breadth?: { pct: number }; mood?: string } | null;
const authorize = () => window.dispatchEvent(new Event("artha:authorize"));
const today = new Date().toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long" });

export default function Dashboard() {
  const universe = useApi<Stock[]>("/api/universe", [], (j) => j.items);
  const news = useApi<NewsItem[]>("/api/news", [], (j) => j.items);
  const flows = useApi<{ fiiStance: string | null } | null>("/api/flows", null, (j) => (j.ok ? j : null));
  const pulse = useApi<Pulse>("/api/pulse", null, (j) => (j.ok ? j : null));
  const events = useApi<EconEvent[]>("/api/events", [], (j) => j.items);
  const board = useApi<{ indices: GlobalRow[] } | null>("/api/global", null, (j) => (j.ok ? j : null));
  const holdings = useApi<RawHolding[]>("/api/holdings", [], (j) => j.items ?? []);
  const aiBrief = useApi<string | null>("/api/brief", null, (j) => (j.ok ? j.brief : null));

  const pf = portfolioSummary(holdings, universe);
  const movers = moversFrom(universe);
  const recos = [...universe].sort((a, b) => b.aiScore - a.aiScore).filter((s) => s.aiRating === "Strong Buy" || s.aiRating === "Buy").slice(0, 3);
  const indices = board?.indices ?? [];
  const breadthPct = pulse?.breadth?.pct ?? null;

  return (
    <div>
      <PageHeader
        eyebrow="Executive briefing"
        title="Executive Briefing"
        description={`Your intelligence workspace for ${today} — live market data and what ARTHA makes of it.`}
        actions={
          <>
            <Link href="/research"><Button variant="secondary"><FlaskConical size={15} />New Research</Button></Link>
            <Link href="/ai-analyst"><Button variant="ai"><Sparkles size={15} />Ask AI</Button></Link>
          </>
        }
      />

      {/* Morning brief — driven by real breadth / flows, no fabricated narrative */}
      <Card variant="ai" className="mb-6 overflow-hidden">
        <div className="grid gap-6 p-6 lg:grid-cols-[1.6fr_1fr]">
          <div>
            <div className="mb-3 flex items-center gap-2"><AiBadge>Market Brief</AiBadge><LiveDot /></div>
            {aiBrief ? (
              // Live AI-generated brief, grounded on real breadth/flows/movers.
              <p className="text-[15px] leading-relaxed text-frost">{aiBrief}</p>
            ) : (
              // Deterministic fallback until the grounded LLM brief lands.
              <p className="text-[15px] leading-relaxed text-frost">
                {breadthPct != null
                  ? <>Market breadth is <span className={cn("font-semibold", breadthPct >= 50 ? "text-up" : "text-down")}>{breadthPct}% advancing</span>{pulse?.mood ? <> ({pulse.mood})</> : null}. </>
                  : <>Live market breadth is loading. </>}
                {flows?.fiiStance && <>Institutional flows read <span className="font-semibold text-frost">{flows.fiiStance}</span>. </>}
                {holdings.length > 0 && <>Your book is <span className={cn("font-semibold", trendClass(pf.dayPnl))}>{pct(pf.dayPnlPct)}</span> today. </>}
                ARTHA surfaces the highest-conviction ideas and upcoming events below.
              </p>
            )}
            <div className="mt-4 flex flex-wrap gap-2">
              {["What's driving market breadth today?", "Summarise my portfolio risk", "Top ideas for this week"].map((q) => (
                <Link key={q} href={`/ai-analyst?q=${encodeURIComponent(q)}`}
                  className="rounded-full bg-void/60 px-3 py-1.5 text-[12px] font-medium text-mist hairline transition-colors hover:text-frost hover:bg-raised">
                  {q}
                </Link>
              ))}
            </div>
          </div>
          <div className="flex items-center justify-center gap-6 rounded-[var(--radius-md)] bg-void/40 p-4 hairline">
            <ScoreRing value={breadthPct != null ? +(breadthPct / 10).toFixed(1) : 0} label="Breadth" />
            <div className="space-y-1.5 text-[12px]">
              <div className="flex items-center gap-2"><span className="h-2 w-2 rounded-full bg-up" /><span className="text-muted">Mood</span><span className="ml-auto font-semibold text-frost">{pulse?.mood ?? "—"}</span></div>
              <div className="flex items-center gap-2"><span className="h-2 w-2 rounded-full bg-accent" /><span className="text-muted">Advancing</span><span className="ml-auto font-semibold text-frost">{breadthPct != null ? `${breadthPct}%` : "—"}</span></div>
              <div className="flex items-center gap-2"><span className="h-2 w-2 rounded-full bg-warn" /><span className="text-muted">FII Flows</span><span className="ml-auto font-semibold text-frost">{flows?.fiiStance ?? "—"}</span></div>
            </div>
          </div>
        </div>
      </Card>

      {/* Market pulse — real global indices */}
      {indices.length > 0 && (
        <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-6">
          {indices.slice(0, 6).map((idx, i) => (
            <Card key={idx.name} delay={i * 0.04} interactive className="p-4">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-semibold uppercase tracking-wide text-muted">{idx.name}</span>
                <DeltaPill pct={idx.changePct ?? 0} />
              </div>
              <div className="mt-1.5 text-[19px] font-semibold text-frost tnum">{idx.price != null ? idx.price.toLocaleString("en-IN") : "—"}</div>
              <div className="mt-2"><Sparkline data={series(idx.name.charCodeAt(0) + idx.name.length, 40, idx.price || 100, 0.006)} width={180} height={30} positive={(idx.changePct ?? 0) >= 0} /></div>
            </Card>
          ))}
        </div>
      )}

      {/* Main grid */}
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        {/* Left column */}
        <div className="space-y-6 xl:col-span-2">
          {/* Portfolio snapshot */}
          <Card>
            <CardHeader icon={<Wallet size={16} />} title="Portfolio Snapshot"
              action={<Link href="/portfolio"><Button variant="ghost" size="sm">Open<ArrowRight size={14} /></Button></Link>} />
            <CardBody>
              {holdings.length > 0 ? (
                <div className="grid grid-cols-2 gap-5 sm:grid-cols-4">
                  <Stat label="Total Value" value={pf.current} prefix="₹" decimals={0} />
                  <Stat label="Day P&L" value={pf.dayPnl} prefix="₹" decimals={0} delta={pf.dayPnlPct} />
                  <Stat label="Overall P&L" value={pf.pnl} prefix="₹" decimals={0} delta={pf.pnlPct} />
                  <div className="flex items-center gap-3"><ScoreRing value={pf.health / 10} label="Health" /></div>
                </div>
              ) : (
                <p className="text-[13px] text-muted">No live holdings. <button onClick={authorize} className="font-medium text-accent hover:underline">Authorize Upstox</button> to load your real portfolio.</p>
              )}
            </CardBody>
          </Card>

          {/* Top movers */}
          <Card>
            <CardHeader icon={<TrendingUp size={16} />} title="Top Movers"
              action={<Link href="/markets"><Button variant="ghost" size="sm">Markets<ArrowRight size={14} /></Button></Link>} />
            <CardBody className="grid gap-x-6 gap-y-1 sm:grid-cols-2">
              <div>
                <div className="mb-1 flex items-center gap-1.5 px-2.5 text-[11px] font-semibold uppercase tracking-wide text-up"><TrendingUp size={12} />Gainers</div>
                {movers.gainers.slice(0, 4).map((s) => <StockRow key={s.symbol} stock={s} spark={false} />)}
              </div>
              <div>
                <div className="mb-1 flex items-center gap-1.5 px-2.5 text-[11px] font-semibold uppercase tracking-wide text-down"><TrendingDown size={12} />Losers</div>
                {movers.losers.slice(0, 4).map((s) => <StockRow key={s.symbol} stock={s} spark={false} />)}
              </div>
            </CardBody>
          </Card>

          {/* News */}
          <div>
            <div className="mb-3 flex items-center justify-between">
              <h3 className="flex items-center gap-2 text-[15px] font-semibold text-frost"><Newspaper size={16} className="text-muted" />Latest Intelligence</h3>
              <Link href="/news"><Button variant="ghost" size="sm">All news<ArrowRight size={14} /></Button></Link>
            </div>
            {news.length > 0 ? (
              <div className="grid gap-3 sm:grid-cols-2">
                {news.slice(0, 4).map((n) => <NewsCard key={n.id} item={n} />)}
              </div>
            ) : <p className="text-[13px] text-muted">No live news available right now.</p>}
          </div>
        </div>

        {/* Right column */}
        <div className="space-y-6">
          {/* AI recommendations */}
          <Card variant="elevated">
            <CardHeader icon={<Sparkles size={16} className="text-ai" />} title="AI Recommendations" subtitle="High-conviction ideas" />
            <CardBody className="space-y-2">
              {recos.length > 0 ? recos.map((s) => (
                <Link key={s.symbol} href={`/stocks/${s.symbol}`}
                  className="flex items-center gap-3 rounded-[var(--radius-sm)] bg-void/50 p-3 transition-colors hover:bg-raised">
                  <ScoreRing value={s.aiScore} size={44} tone="ai" />
                  <div className="min-w-0">
                    <div className="text-[13px] font-semibold text-frost">{s.symbol}</div>
                    <div className="text-[11px] text-muted truncate max-w-[110px]">{s.name}</div>
                  </div>
                  <div className="ml-auto text-right"><RatingBadge rating={s.aiRating} /><div className={cn("mt-1 text-[12px] font-medium tnum", trendClass(s.changePct))}>{pct(s.changePct)}</div></div>
                </Link>
              )) : <p className="text-[13px] text-muted">Ranked ideas appear once the universe loads.</p>}
            </CardBody>
          </Card>

          {/* Watchlist */}
          <Card>
            <CardHeader icon={<TrendingUp size={16} />} title="Watchlist"
              action={<Link href="/watchlists"><Button variant="ghost" size="sm">Edit</Button></Link>} />
            <CardBody className="space-y-0.5">
              {universe.slice(0, 5).map((s) => <StockRow key={s.symbol} stock={s} />)}
            </CardBody>
          </Card>

          {/* Upcoming events */}
          <Card>
            <CardHeader icon={<CalendarClock size={16} />} title="Upcoming Events"
              action={<Link href="/calendar"><Button variant="ghost" size="sm">Calendar</Button></Link>} />
            <CardBody className="space-y-1">
              {events.length > 0 ? events.slice(0, 4).map((e, i) => (
                <div key={i} className="flex items-center gap-3 rounded-[var(--radius-sm)] px-2.5 py-2 hover:bg-raised/60">
                  <div className="flex h-9 w-9 shrink-0 flex-col items-center justify-center rounded-[8px] bg-void hairline text-[10px] font-semibold text-muted tnum">{e.time}</div>
                  <div className="min-w-0 flex-1"><div className="text-[12.5px] font-medium text-frost truncate">{e.title}</div><div className="text-[11px] text-muted">{e.country}</div></div>
                  <ImpactBadge impact={e.impact} />
                </div>
              )) : <p className="text-[13px] text-muted">No live economic calendar feed wired.</p>}
            </CardBody>
          </Card>
        </div>
      </div>
    </div>
  );
}
