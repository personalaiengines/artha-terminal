"use client";
import { use } from "react";
import Link from "next/link";
import { notFound } from "next/navigation";
import {
  Sparkles, Star, Bell, Plus, ShieldCheck, Activity, Layers,
  ShieldAlert, BarChart3, Building2,
} from "lucide-react";
import { Card, CardHeader, CardBody } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge, RatingBadge, AiBadge } from "@/components/ui/badge";
import { DeltaPill, ScoreRing, HealthBar } from "@/components/ui/stat";
import { Tabs, Segmented, Avatar, LiveDot } from "@/components/ui/primitives";
import { CandleChart } from "@/components/ui/candles";
import { DataGrid, Column } from "@/components/ui/data-grid";
import { EmptyState } from "@/components/ui/primitives";
import { Stock } from "@/lib/data";
import { useApi } from "@/lib/use-api";
import { POLL } from "@/lib/poll";
import { useEnsureFresh } from "@/lib/use-fresh";
import { useMarketWs } from "@/lib/use-ws";
import { inr, compactCr, num, mcap, pct, changeText, trendClass } from "@/lib/format";
import { useUI } from "@/components/layout/ui-store";
import { cn } from "@/lib/utils";
import { useState, useEffect } from "react";

type Candle = { t: string; open: number; high: number; low: number; close: number; volume: number };

export default function StockResearch({ params }: { params: Promise<{ symbol: string }> }) {
  const { symbol } = use(params);
  // No mock fallback: ok:false when the API has no data for this symbol.
  const { stock, history: bars } = useApi<{ stock: Stock | null; history: Candle[] }>(
    `/api/stock/${symbol}`, { stock: null, history: [] }, (j) => ({ stock: j.stock, history: j.history ?? [] }), POLL.stock
  );
  const universe = useApi<Stock[]>("/api/universe", [], (j) => j.items, POLL.universe);
  useEnsureFresh([symbol.toUpperCase()]);
  const [tf, setTf] = useState("1D");
  const { subscribe } = useMarketWs();
  const [live, setLive] = useState<{ price: number; change: number | null; changePct: number | null } | null>(null);
  useEffect(() => {
    if (!stock) return;
    setLive(null); // reset the overlay on symbol change so stale ticks don't leak across pages
    return subscribe([stock.symbol], (tick) => {
      if (typeof tick.ltp !== "number") return;
      const prevClose = typeof tick.close === "number" ? tick.close : null;
      setLive({
        price: tick.ltp,
        change: prevClose !== null ? tick.ltp - prevClose : null,
        changePct: prevClose ? ((tick.ltp - prevClose) / prevClose) * 100 : null,
      });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stock?.symbol]);
  if (!stock) {
    return (
      <Card><CardBody><EmptyState icon={<Activity size={22} />} title={`No live data for ${symbol.toUpperCase()}`}
        description="This symbol isn't in the ARTHA database, or the API is unreachable." /></CardBody></Card>
    );
  }
  const closes = bars.map((b) => b.close);
  const hasBars = closes.length > 0;
  const hi = hasBars ? Math.max(...closes) : 0, lo = hasBars ? Math.min(...closes) : 0;
  const levels = hasBars ? [
    { price: +(hi * 0.995).toFixed(0), label: "Resistance", color: "#f4586a" },
    { price: +((hi + lo) / 2).toFixed(0), label: "Pivot", color: "#f5a623" },
    { price: +(lo * 1.005).toFixed(0), label: "Support", color: "#10b981" },
  ] : [];
  const peers = universe.filter((s) => s.sector === stock.sector && s.symbol !== stock.symbol).slice(0, 5);

  return (
    <div>
      {/* Company header */}
      <Card variant="elevated" className="mb-6 overflow-hidden">
        <div className="relative p-6">
          <div className="absolute inset-x-0 top-0 h-24 bg-gradient-to-b from-accent/8 to-transparent" />
          <div className="relative flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
            <div className="flex items-start gap-4">
              <Avatar symbol={stock.symbol} size={56} />
              <div>
                <div className="flex items-center gap-2.5">
                  <h1 className="text-[26px] font-bold tracking-tight text-frost leading-none">{stock.symbol}</h1>
                  <Badge tone="neutral">NSE</Badge>
                  <span className="flex items-center gap-1 text-[11px] text-up"><ShieldCheck size={12} />Verified</span>
                </div>
                <p className="mt-1.5 text-[14px] text-mist">{stock.name}</p>
                <div className="mt-3 flex items-end gap-3">
                  <span className="text-[32px] font-bold text-frost tnum leading-none">{inr(live?.price ?? stock.price)}</span>
                  <DeltaPill value={live?.change ?? stock.change} pct={live?.changePct ?? stock.changePct} className="mb-1" />
                  {live && <LiveDot />}
                </div>
                <div className="mt-2 flex items-center gap-3 text-[11px] text-muted">
                  <span>{stock.sector}</span><span>·</span>
                  <span>Mkt Cap {mcap(stock.mcapCr)}</span><span>·</span>
                  <span className="tnum">52W {inr(stock.low52, { decimals: 0 })}–{inr(stock.high52, { decimals: 0 })}</span>
                </div>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Link href="/watchlists"><Button variant="secondary" size="sm"><Star size={14} />Watch</Button></Link>
              <Link href="/alerts"><Button variant="secondary" size="sm"><Bell size={14} />Alert</Button></Link>
              <Link href="/portfolio"><Button variant="secondary" size="sm"><Plus size={14} />Position</Button></Link>
              <Link href={`/ai-analyst?q=${encodeURIComponent(`Give me a deep-dive analysis on ${stock.symbol}`)}`}><Button variant="ai" size="sm"><Sparkles size={14} />AI Deep-Dive</Button></Link>
            </div>
          </div>

          {/* Rating strip */}
          <div className="relative mt-6 grid grid-cols-2 gap-4 rounded-[var(--radius-md)] bg-void/50 p-4 hairline sm:grid-cols-4 lg:grid-cols-6">
            <RatingTile label="AI Rating"><div className="flex items-center gap-2"><ScoreRing value={stock.aiScore} size={40} tone="ai" /><RatingBadge rating={stock.aiRating} /></div></RatingTile>
            <RatingTile label="Health Score"><div className="w-full">{stock.health == null ? <div className="text-[16px] font-bold text-faint tnum">—</div> : <><div className="text-[16px] font-bold text-frost tnum">{stock.health}<span className="text-[11px] text-muted">/100</span></div><HealthBar value={stock.health} /></>}</div></RatingTile>
            <RatingTile label="P/E · P/B"><span className="text-[16px] font-bold text-frost tnum">{num(stock.pe)} · {num(stock.pb)}</span></RatingTile>
            <RatingTile label="ROE"><span className="text-[16px] font-bold text-frost tnum">{num(stock.roe, { suffix: "%" })}</span></RatingTile>
            <RatingTile label="RSI (14)"><span className="text-[16px] font-bold text-frost tnum">{stock.rsi != null ? stock.rsi.toFixed(0) : "—"}</span></RatingTile>
            <RatingTile label="Div Yield"><span className="text-[16px] font-bold text-frost tnum">{num(stock.divYield, { suffix: "%" })}</span></RatingTile>
          </div>
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        {/* Chart + tabs */}
        <div className="space-y-6 xl:col-span-2">
          <Card>
            <CardHeader icon={<Activity size={16} />} title="Price & Key Levels" subtitle={`${stock.symbol} · candlestick`}
              action={<Segmented size="sm" value={tf} onChange={setTf} options={["1D", "1W", "1M", "1Y", "5Y"].map((v) => ({ label: v, value: v }))} />} />
            <CardBody className="pt-0">
              <CandleChart data={bars} levels={levels} height={360} />
              <div className="mt-3 flex flex-wrap items-center gap-4 text-[11px]">
                {levels.map((l) => <span key={l.label} className="flex items-center gap-1.5"><span className="h-2 w-4 rounded-full" style={{ background: l.color }} /><span className="text-muted">{l.label}</span><span className="font-medium text-frost tnum">{inr(l.price, { decimals: 0 })}</span></span>)}
              </div>
            </CardBody>
          </Card>

          <Card>
            <CardBody className="pt-5">
              <Tabs tabs={[
                { id: "fund", label: "Fundamentals", icon: <Building2 size={14} /> },
                { id: "tech", label: "Technicals", icon: <BarChart3 size={14} /> },
                { id: "peers", label: "Peers", icon: <Layers size={14} /> },
                { id: "risk", label: "Risk", icon: <ShieldAlert size={14} /> },
              ]}>
                {(active) => (
                  <>
                    {active === "fund" && <Fundamentals stock={stock} />}
                    {active === "tech" && <Technicals stock={stock} bars={bars} />}
                    {active === "peers" && <Peers peers={peers} self={stock} />}
                    {active === "risk" && <RiskPanel stock={stock} />}
                  </>
                )}
              </Tabs>
            </CardBody>
          </Card>
        </div>

        {/* AI side rail */}
        <div className="space-y-6">
          <Card variant="ai">
            <CardHeader icon={<Sparkles size={16} className="text-ai" />} title="AI Score"
              subtitle={stock.scoreKind === "scorecard" ? "Fundamentals scorecard (0-10)"
                : stock.scoreKind === "momentum" ? "Momentum only — no fundamentals yet (0-10)"
                : "Not enough data to score"} action={<AiBadge>Live</AiBadge>} />
            <CardBody className="space-y-4">
              {stock.aiScore == null || stock.aiRating == null ? (
                <p className="text-[13px] leading-relaxed text-muted">
                  No score for {stock.name} — this symbol has no price history in the
                  database yet, so there is nothing to compute momentum from.
                </p>
              ) : (
                <p className="text-[13px] leading-relaxed text-mist">
                  {stock.name} screens as <span className="font-semibold text-frost">{stock.aiRating.toLowerCase()}</span> at a score of {stock.aiScore}/10, computed from
                  {stock.scoreKind === "scorecard"
                    ? " valuation, growth, financial health, momentum and sector sub-scores."
                    : <> real price momentum only{stock.rsi != null ? <> and RSI ({stock.rsi.toFixed(0)})</> : ""} — no fundamentals for this symbol yet.</>}
                  {stock.changePct != null && <> Momentum is
                    <span className={trendClass(stock.changePct)}> {stock.changePct >= 0 ? "constructive" : "soft"}</span> near current levels.</>}
                </p>
              )}
              <Link href={`/ai-analyst?q=${encodeURIComponent(`Tell me more about ${stock.symbol}`)}`} className="block">
                <Button variant="ai" size="md" className="w-full justify-center"><Sparkles size={14} />Ask a follow-up</Button>
              </Link>
            </CardBody>
          </Card>

          <AiNarrative symbol={stock.symbol} />
        </div>
      </div>
    </div>
  );
}

// Grounded NIM analyst read (services/stock_analysis_llm.py): real yfinance/DB
// facts, LLM only interprets. Slow (up to ~90s cold) — fetched on demand, not
// on page load, so the page never blocks on it.
function AiNarrative({ symbol }: { symbol: string }) {
  const [state, setState] = useState<"idle" | "loading" | "done" | "error">("idle");
  const [text, setText] = useState("");

  const generate = async () => {
    setState("loading");
    try {
      const r = await fetch(`/api/stock/${symbol}/analysis`).then((x) => x.json());
      if (r?.ok && r.markdown) { setText(r.markdown); setState("done"); }
      else setState("error");
    } catch {
      setState("error");
    }
  };

  return (
    <Card>
      <CardHeader icon={<Building2 size={16} />} title="AI Analyst Read" subtitle="Grounded in live fundamentals · NIM" />
      <CardBody>
        {state === "idle" && (
          <Button variant="secondary" size="md" className="w-full justify-center" onClick={generate}>
            <Sparkles size={14} />Generate analysis
          </Button>
        )}
        {state === "loading" && <p className="py-4 text-center text-[12.5px] text-muted">Analysing live fundamentals… (up to ~90s)</p>}
        {state === "error" && <p className="py-4 text-center text-[12.5px] text-down">No live fundamentals available for {symbol}, or the AI backend is unreachable.</p>}
        {state === "done" && (
          <div className="space-y-2 text-[12.5px] leading-relaxed text-mist">
            {text.split("\n").map((line, i) => line.startsWith("### ")
              ? <div key={i} className="pt-2 text-[12px] font-semibold uppercase tracking-wide text-accent">{line.slice(4)}</div>
              : line.trim() ? <p key={i}>{line}</p> : null)}
          </div>
        )}
      </CardBody>
    </Card>
  );
}

function RatingTile({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-[10px] font-semibold uppercase tracking-wide text-muted">{label}</span>
      {children}
    </div>
  );
}

function KV({ k, v, tone }: { k: string; v: string; tone?: string }) {
  return (
    <div className="flex items-center justify-between border-b border-line/50 py-2">
      <span className="text-[12.5px] text-muted">{k}</span>
      <span className={cn("text-[13px] font-semibold tnum", tone ?? "text-frost")}>{v}</span>
    </div>
  );
}

function Fundamentals({ stock }: { stock: Stock }) {
  return (
    <div className="grid gap-x-8 gap-y-0 sm:grid-cols-2">
      <div>
        <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-accent">Valuation</div>
        <KV k="P/E Ratio" v={`${stock.pe}×`} />
        <KV k="P/B Ratio" v={`${stock.pb}×`} />
        <KV k="Dividend Yield" v={`${stock.divYield}%`} />
        <KV k="Market Cap" v={mcap(stock.mcapCr)} />
        <div className="mb-1 mt-4 text-[11px] font-semibold uppercase tracking-wide text-accent">Profitability</div>
        <KV k="ROE" v={`${stock.roe}%`} tone="text-up" />
        <KV k="Return 1Y" v={stock.return1y != null ? pct(stock.return1y) : "—"} tone={stock.return1y != null ? trendClass(stock.return1y) : undefined} />
      </div>
      <div>
        <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-accent">Leverage & Quality</div>
        <KV k="Debt / Equity" v={stock.debtEquity == null ? "—" : `${stock.debtEquity}×`} tone={stock.debtEquity == null ? undefined : stock.debtEquity > 1 ? "text-warn" : "text-up"} />
        <KV k="Health Score" v={`${stock.health}/100`} />
        <div className="mb-1 mt-4 text-[11px] font-semibold uppercase tracking-wide text-accent">Range</div>
        <KV k="52W High" v={inr(stock.high52, { decimals: 0 })} />
        <KV k="52W Low" v={inr(stock.low52, { decimals: 0 })} />
        <KV k="AI Score" v={`${stock.aiScore}/10`} tone="text-ai" />
      </div>
    </div>
  );
}

// Real ATR(14) from live OHLC bars (Wilder's true range average). Returns null
// without enough history — never fabricated.
function atr14(bars: Candle[]): number | null {
  if (bars.length < 15) return null;
  const trs: number[] = [];
  for (let i = 1; i < bars.length; i++) {
    const { high, low, close: prevClose } = { high: bars[i].high, low: bars[i].low, close: bars[i - 1].close };
    trs.push(Math.max(high - low, Math.abs(high - prevClose), Math.abs(low - prevClose)));
  }
  const last14 = trs.slice(-14);
  return last14.reduce((a, b) => a + b, 0) / last14.length;
}

function Technicals({ stock, bars }: { stock: Stock; bars: Candle[] }) {
  const atr = atr14(bars);
  const rows: [string, string, string][] = [
    ["RSI (14)", stock.rsi != null ? stock.rsi.toFixed(1) : "—", stock.rsi == null ? "—" : stock.rsi > 70 ? "Overbought" : stock.rsi < 30 ? "Oversold" : "Neutral"],
    ["50 DMA", stock.dma50 != null ? inr(stock.dma50, { decimals: 0 }) : "—", stock.dma50 == null || stock.price == null ? "—" : stock.price >= stock.dma50 ? "Above" : "Below"],
    ["200 DMA", stock.dma200 != null ? inr(stock.dma200, { decimals: 0 }) : "—", stock.dma200 == null || stock.price == null ? "—" : stock.price >= stock.dma200 ? "Above" : "Below"],
    ["ATR (14)", atr != null ? atr.toFixed(1) : "—", "—"],
    ["Beta", stock.beta != null ? stock.beta.toFixed(2) : "—", "—"],
  ];
  return (
    <div className="grid gap-x-8 sm:grid-cols-2">
      {rows.map(([k, v, s]) => (
        <div key={k} className="flex items-center justify-between border-b border-line/50 py-2.5">
          <span className="text-[12.5px] text-muted">{k}</span>
          <span className="flex items-center gap-2">
            <span className="text-[13px] font-semibold text-frost tnum">{v}</span>
            <Badge tone={s === "Above" ? "up" : s === "Below" || s === "Overbought" ? "down" : "neutral"}>{s}</Badge>
          </span>
        </div>
      ))}
    </div>
  );
}

function Peers({ peers, self }: { peers: Stock[]; self: Stock }) {
  const { changeMode } = useUI();
  const rows = [self, ...peers];
  const columns: Column<Stock>[] = [
    { key: "symbol", header: "Company", cell: (s) => <span className="flex items-center gap-2"><Avatar symbol={s.symbol} size={26} /><span className="font-medium">{s.symbol}{s.symbol === self.symbol && <span className="ml-1.5 text-[10px] text-accent">•you</span>}</span></span> },
    { key: "price", header: "Price", align: "right", sortable: true, sortValue: (s) => s.price, cell: (s) => <span className="tnum">{inr(s.price)}</span> },
    { key: "chg", header: "Chg%", align: "right", sortable: true, sortValue: (s) => s.changePct, cell: (s) => <span className={cn("tnum font-medium", trendClass(s.changePct))}>{changeText(s.changePct, s.change, changeMode)}</span> },
    { key: "pe", header: "P/E", align: "right", sortable: true, sortValue: (s) => s.pe, cell: (s) => <span className="tnum">{s.pe}</span> },
    { key: "roe", header: "ROE", align: "right", sortable: true, sortValue: (s) => s.roe, cell: (s) => <span className="tnum">{s.roe}%</span> },
    { key: "ai", header: "AI", align: "right", sortable: true, sortValue: (s) => s.aiScore, cell: (s) => <span className="tnum font-semibold text-ai">{s.aiScore}</span> },
  ];
  return <DataGrid columns={columns} rows={rows} rowKey={(s) => s.symbol} />;
}

// Only flags computable from real fundamentals we actually have (P/E, D/E).
// Promoter-pledge / OCF-vs-PAT / interest-coverage need data ARTHA doesn't
// source yet — no fabricated always-pass rows for those.
function RiskPanel({ stock }: { stock: Stock }) {
  const hasDE = !!stock.debtEquity, hasPE = !!stock.pe;
  const flags = [
    hasDE
      ? { name: "Debt / Equity", severity: stock.debtEquity! > 1 ? "fail" : stock.debtEquity! > 0.6 ? "warn" : "pass", msg: `D/E at ${stock.debtEquity}× for ${stock.sector}` }
      : { name: "Debt / Equity", severity: "unknown", msg: "No debt/equity data available" },
    hasPE
      ? { name: "Valuation Stretch", severity: stock.pe! > 40 ? "warn" : "pass", msg: `P/E ${stock.pe}×` }
      : { name: "Valuation Stretch", severity: "unknown", msg: "No P/E data available" },
  ] as const;
  const tone = { pass: "up", warn: "warn", fail: "down", unknown: "neutral" } as const;
  return (
    <div className="space-y-2">
      {flags.map((f) => (
        <div key={f.name} className="flex items-center gap-3 rounded-[var(--radius-sm)] bg-void/40 p-3 hairline">
          <span className={cn("h-2 w-2 rounded-full", f.severity === "pass" ? "bg-up" : f.severity === "warn" ? "bg-warn" : f.severity === "fail" ? "bg-down" : "bg-muted")} />
          <div className="min-w-0"><div className="text-[13px] font-medium text-frost">{f.name}</div><div className="text-[11.5px] text-muted">{f.msg}</div></div>
          <Badge tone={tone[f.severity as keyof typeof tone]} className="ml-auto">{f.severity}</Badge>
        </div>
      ))}
      <p className="pt-2 text-[11px] text-muted">Rule-based flags from live fundamentals only · not AI-generated.</p>
    </div>
  );
}
