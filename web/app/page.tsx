"use client";
import { useState } from "react";
import Link from "next/link";
import { ArrowRight, Sparkles, TrendingUp, TrendingDown, CalendarClock, Newspaper, Wallet, FlaskConical } from "lucide-react";
import { PageHeader } from "@/components/widgets/page-header";
import { Card, CardHeader, CardBody } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { AiBadge, RatingBadge, ImpactBadge } from "@/components/ui/badge";
import { Stat, ScoreRing } from "@/components/ui/stat";
import { LiveDot } from "@/components/ui/primitives";
import { StockRow } from "@/components/widgets/stock-row";
import { NewsCard } from "@/components/widgets/news-card";
import { IndexStrip } from "@/components/widgets/india-indices";
import { Markdown } from "@/components/ui/markdown";
import { Stock, NewsItem, EconEvent, blankStock } from "@/lib/data";
import { moversFrom, portfolioSummary, RawHolding } from "@/lib/portfolio";
import { useApi } from "@/lib/use-api";
import { useLivePrices, withLivePrices } from "@/lib/use-live-prices";
import { POLL } from "@/lib/poll";
import { useSparklines } from "@/lib/use-sparklines";
import { changeText, trendClass } from "@/lib/format";
import { useUI } from "@/components/layout/ui-store";
import { cn } from "@/lib/utils";

type MoverGroup = { gainers: Stock[]; losers: Stock[]; count: number };
type MoversPayload = { gainers: Stock[]; losers: Stock[]; groups?: Record<string, MoverGroup> };
type Pulse = { breadth?: { pct: number }; mood?: string } | null;
const authorize = () => window.dispatchEvent(new Event("artha:authorize"));
const today = new Date().toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long" });

export default function Dashboard() {
  const { changeMode } = useUI();
  const universe = useApi<Stock[]>("/api/universe", [], (j) => j.items, POLL.universe);
  const news = useApi<NewsItem[]>("/api/news", [], (j) => j.items, POLL.news);
  const flows = useApi<{ fiiStance: string | null } | null>("/api/flows", null, (j) => (j.ok ? j : null), POLL.flows);
  const pulse = useApi<Pulse>("/api/pulse", null, (j) => (j.ok ? j : null), POLL.pulse);
  const events = useApi<EconEvent[]>("/api/events", [], (j) => j.items, POLL.events);
  const holdings = useApi<RawHolding[]>("/api/holdings", [], (j) => j.items ?? [], POLL.holdings);
  const aiBrief = useApi<string | null>("/api/brief", null, (j) => (j.ok ? j.brief : null), POLL.brief);
  const liveMovers = useApi<MoversPayload | null>("/api/movers", null, (j) => (j.ok ? j : null), POLL.movers);
  const watchlists = useApi<{ id: number; name: string; symbols: string[] }[]>("/api/watchlists", [], (j) => (j.ok ? j.items : []), POLL.watchlists);

  const pf = portfolioSummary(holdings, universe);
  const movers = liveMovers ?? moversFrom(universe);

  // Movers scope: "Market" plus whatever index/sector slices the API returned.
  const [scope, setScope] = useState("Market");
  const groups = liveMovers?.groups ?? {};
  const scopes = ["Market", ...Object.keys(groups)];
  const scopedRaw = scope === "Market" ? movers : (groups[scope] ?? { gainers: [], losers: [] });
  const scopeCount = groups[scope]?.count ?? 0;
  const watchlistSymbols = watchlists[0]?.symbols ?? [];
  const watchlistRows = watchlistSymbols
    .map((sym) => universe.find((s) => s.symbol === sym) ?? blankStock({ symbol: sym }))
    .slice(0, 5);
  const watchSpark = useSparklines(watchlistRows.map((s) => s.symbol));

  // Live ticks for exactly what this page renders: the movers on show, the
  // watchlist rows and every held symbol.
  const live = useLivePrices([
    ...scopedRaw.gainers.slice(0, 4).map((s) => s.symbol),
    ...scopedRaw.losers.slice(0, 4).map((s) => s.symbol),
    ...watchlistRows.map((s) => s.symbol),
    ...holdings.map((h) => h.symbol),
  ]);
  const scoped = {
    gainers: withLivePrices(scopedRaw.gainers, live),
    losers: withLivePrices(scopedRaw.losers, live),
  };
  const liveWatchlist = withLivePrices(watchlistRows, live);
  const scored = universe.filter((s) => typeof s.aiScore === "number").length;
  const topScored = universe
    .filter((s) => typeof s.aiScore === "number" && s.aiRating === "WATCH")
    .sort((a, b) => b.aiScore! - a.aiScore!)
    .slice(0, 3);
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
              // Live AI round-up, grounded on real index levels / breadth /
              // sectors / movers / flows / global cues. Markdown, because it's
              // now a sectioned brief rather than one sentence.
              <Markdown text={aiBrief} className="text-[14px] leading-relaxed text-frost" />
            ) : (
              // Deterministic fallback until the grounded LLM brief lands.
              <p className="text-[15px] leading-relaxed text-frost">
                {breadthPct != null
                  ? <>Market breadth is <span className={cn("font-semibold", breadthPct >= 50 ? "text-up" : "text-down")}>{breadthPct}% advancing</span>{pulse?.mood ? <> ({pulse.mood})</> : null}. </>
                  : <>Live market breadth is loading. </>}
                {flows?.fiiStance && <>Institutional flows read <span className="font-semibold text-frost">{flows.fiiStance}</span>. </>}
                {holdings.length > 0 && <>Your book is <span className={cn("font-semibold", trendClass(pf.dayPnl))}>{changeText(pf.dayPnlPct, pf.dayPnl, changeMode)}</span> today. </>}
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
          {/* self-start: the brief is now several sections tall, and a vertically
              centred stat panel next to it floats in the middle of nowhere. */}
          <div className="flex items-center justify-center gap-6 self-start rounded-[var(--radius-md)] bg-void/40 p-4 hairline">
            <ScoreRing value={breadthPct != null ? +(breadthPct / 10).toFixed(1) : 0} label="Breadth" />
            <div className="space-y-1.5 text-[12px]">
              <div className="flex items-center gap-2"><span className="h-2 w-2 rounded-full bg-up" /><span className="text-muted">Mood</span><span className="ml-auto font-semibold text-frost">{pulse?.mood ?? "—"}</span></div>
              <div className="flex items-center gap-2"><span className="h-2 w-2 rounded-full bg-accent" /><span className="text-muted">Advancing</span><span className="ml-auto font-semibold text-frost">{breadthPct != null ? `${breadthPct}%` : "—"}</span></div>
              <div className="flex items-center gap-2"><span className="h-2 w-2 rounded-full bg-warn" /><span className="text-muted">FII Flows</span><span className="ml-auto font-semibold text-frost">{flows?.fiiStance ?? "—"}</span></div>
            </div>
          </div>
        </div>
      </Card>

      {/* Home board — Nifty / Sensex / Bank Nifty / Midcap / VIX + Gift Nifty,
          live and session-aware. This slot used to render the *global* board
          (S&P, Nasdaq, FTSE); those now live on the Markets page. */}
      <IndexStrip />

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
                  <div className="flex items-center gap-3"><ScoreRing value={pf.health == null ? null : pf.health / 10} label="Health" /></div>
                </div>
              ) : (
                <p className="text-[13px] text-muted">No live holdings. <button onClick={authorize} className="font-medium text-accent hover:underline">Authorize Upstox</button> to load your real portfolio.</p>
              )}
            </CardBody>
          </Card>

          {/* Top movers, sliced by index (NIFTY 50 / Bank Nifty / Sensex) and
              sector (IT, Pharma, …). Membership is curated in
              services/nifty50.py — symbol_master.sector is NULL for every row,
              so the DB cannot supply it. */}
          <Card>
            <CardHeader icon={<TrendingUp size={16} />} title="Top Movers"
              subtitle={scope === "Market" ? "Market-wide" : `${scope} · ${scopeCount} stocks`}
              action={<Link href="/markets"><Button variant="ghost" size="sm">Markets<ArrowRight size={14} /></Button></Link>} />
            <div className="-mb-1 flex gap-1 overflow-x-auto px-4 pb-2">
              {scopes.map((g) => (
                <button key={g} onClick={() => setScope(g)}
                  className={cn(
                    "shrink-0 rounded-full px-2.5 py-1 text-[11.5px] font-medium transition-colors",
                    g === scope ? "bg-accent/15 text-accent" : "text-muted hover:bg-raised hover:text-frost"
                  )}>
                  {g}
                </button>
              ))}
            </div>
            <CardBody className="grid gap-x-6 gap-y-1 sm:grid-cols-2">
              <div>
                <div className="mb-1 flex items-center gap-1.5 px-2.5 text-[11px] font-semibold uppercase tracking-wide text-up"><TrendingUp size={12} />Gainers</div>
                {scoped.gainers.length > 0
                  ? scoped.gainers.slice(0, 4).map((s) => <StockRow key={s.symbol} stock={s} spark={false} />)
                  : <p className="px-2.5 py-2 text-[12px] text-muted">Nothing up in {scope} today.</p>}
              </div>
              <div>
                <div className="mb-1 flex items-center gap-1.5 px-2.5 text-[11px] font-semibold uppercase tracking-wide text-down"><TrendingDown size={12} />Losers</div>
                {scoped.losers.length > 0
                  ? scoped.losers.slice(0, 4).map((s) => <StockRow key={s.symbol} stock={s} spark={false} />)
                  : <p className="px-2.5 py-2 text-[12px] text-muted">Nothing down in {scope} today.</p>}
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
            {/* Subtitle names the actual basis. The score behind these is
                computed_metrics.analysis_score (the fundamentals ScorecardEngine)
                when the Analysis Score ETL has run, otherwise a momentum-only
                heuristic over 1y/6m return + RSI — calling either one an "AI
                recommendation" with no qualifier overstates what it knows. */}
            <CardHeader icon={<Sparkles size={16} className="text-ai" />} title="AI Recommendations"
              subtitle={topScored.length === 0 ? "High-conviction ideas"
                : topScored.every((s) => s.scoreKind === "momentum")
                  ? `Momentum-ranked · ${scored} of ${universe.length} symbols scored`
                  : `Scorecard-ranked · ${scored} of ${universe.length} symbols scored`} />
            <CardBody className="space-y-2">
              {topScored.length > 0 ? topScored.map((s) => (
                <Link key={s.symbol} href={`/stocks/${s.symbol}`}
                  className="flex items-center gap-3 rounded-[var(--radius-sm)] bg-void/50 p-3 transition-colors hover:bg-raised">
                  <ScoreRing value={s.aiScore} size={44} tone="ai" />
                  <div className="min-w-0">
                    <div className="text-[13px] font-semibold text-frost">{s.symbol}</div>
                    <div className="text-[11px] text-muted truncate max-w-[110px]">{s.name}</div>
                  </div>
                  <div className="ml-auto text-right"><RatingBadge rating={s.aiRating} /><div className={cn("mt-1 text-[12px] font-medium tnum", trendClass(s.changePct))}>{changeText(s.changePct, s.change, changeMode)}</div></div>
                </Link>
              )) : (
                <p className="text-[13px] text-muted">
                  {universe.length > 0 && scored === 0
                    ? <>No symbol has a score yet — run <span className="font-medium text-frost">Analysis Score ETL</span> from <Link href="/settings" className="text-accent hover:underline">Settings</Link> to rank the universe.</>
                    : <>Ranked ideas appear once the universe loads.</>}
                </p>
              )}
            </CardBody>
          </Card>

          {/* Watchlist */}
          <Card>
            <CardHeader icon={<TrendingUp size={16} />} title={watchlists[0]?.name ?? "Watchlist"}
              action={<Link href="/watchlists"><Button variant="ghost" size="sm">Edit</Button></Link>} />
            <CardBody className="space-y-0.5">
              {liveWatchlist.length > 0
                ? liveWatchlist.map((s) => <StockRow key={s.symbol} stock={s} sparkData={watchSpark[s.symbol]} />)
                : <p className="text-[13px] text-muted">No watchlist yet — create one to track symbols here.</p>}
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
