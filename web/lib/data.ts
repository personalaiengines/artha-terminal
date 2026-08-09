// Shared UI types + seeded chart-shape generators for ARTHA. The mock DATA
// arrays have been removed — every page now reads real data from /api/* and
// renders honest empty/loading states when a module isn't wired. What remains
// here is (a) the typed shapes the UI renders and (b) deterministic sparkline/
// candle GEOMETRY (series/candles) used only where no per-symbol history feed
// exists yet — visual scaffolding, not fabricated fundamentals.
//
// The option-chain generator that used to live here is GONE: it invented OI, IV
// and LTP per strike, indistinguishable from a live Upstox chain, on the one
// page where a user reads prices off the screen. /options now renders "no live
// chain for this expiry" instead.

// Every numeric here is nullable because the API genuinely returns null for
// them: only a fraction of the 5000+ symbol universe has fundamentals or a
// computed score. These were typed non-null and coerced to 0, which is why
// stocks with no data rendered "P/E 0", "ROE 0%", "₹0" market cap and a
// confident "5.0 / Hold" score. Null must stay null all the way to the
// formatter, which renders "—".
export type Stock = {
  symbol: string;
  name: string;
  sector: string;
  price: number | null;
  change: number | null;      // absolute
  changePct: number | null;   // %
  mcapCr: number | null;
  volume: number | null;      // shares
  pe: number | null;
  pb: number | null;
  divYield: number | null;
  roe: number | null;
  debtEquity: number | null;
  aiScore: number | null;     // 0-10
  // Which engine produced aiScore: a full fundamentals scorecard, or the
  // momentum-only fallback. Null when there was no score at all.
  scoreKind?: "scorecard" | "momentum" | null;
  // True when this row's price came from the live tick stream rather than the
  // last stored close (see lib/use-live-prices.ts).
  isLive?: boolean;
  aiRating: "WATCH" | "HOLD" | "REVIEW" | null;
  health: number | null;      // 0-100
  high52: number | null;
  low52: number | null;
  // Optional real technicals (only present when the DB has computed them).
  beta?: number | null;
  rsi?: number | null;
  dma50?: number | null;
  dma200?: number | null;
  return1y?: number | null;
};

// Build a full Stock from whatever real fields the API returned. Unknown
// fields stay null (never 0, never mock) so they render as "—" downstream.
export function blankStock(p: Partial<Stock> & { symbol: string }): Stock {
  const aiScore = p.aiScore ?? null;
  return {
    symbol: p.symbol, name: p.name ?? p.symbol, sector: p.sector ?? "—",
    price: p.price ?? null, change: p.change ?? null, changePct: p.changePct ?? null,
    mcapCr: p.mcapCr ?? null, volume: p.volume ?? null,
    pe: p.pe ?? null, pb: p.pb ?? null, divYield: p.divYield ?? null,
    roe: p.roe ?? null, debtEquity: p.debtEquity ?? null,
    aiScore, scoreKind: p.scoreKind ?? null,
    // The band thresholds live once, in Python (api/server.py::_RATING); the
    // server sends aiRating on every row. No client-side fallback label.
    aiRating: p.aiRating ?? null, health: p.health ?? null,
    high52: p.high52 ?? null, low52: p.low52 ?? null,
  };
}

// Seeded PRNG for reproducible sparklines/series.
function mulberry(seed: number) {
  return function () {
    seed |= 0; seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function series(seed: number, points = 48, base = 100, vol = 0.02): number[] {
  const r = mulberry(seed);
  let v = base;
  const out: number[] = [];
  for (let i = 0; i < points; i++) {
    v = Math.max(1, v * (1 + (r() - 0.48) * vol));
    out.push(+v.toFixed(2));
  }
  return out;
}

export function candles(seed: number, points = 90, base = 2400) {
  const r = mulberry(seed);
  let v = base;
  const out = [];
  const now = Date.now();
  for (let i = points; i > 0; i--) {
    const open = v;
    const drift = (r() - 0.47) * 0.03;
    const close = Math.max(1, open * (1 + drift));
    const high = Math.max(open, close) * (1 + r() * 0.012);
    const low = Math.min(open, close) * (1 - r() * 0.012);
    v = close;
    out.push({
      t: new Date(now - i * 86400000).toISOString().slice(0, 10),
      open: +open.toFixed(2), high: +high.toFixed(2),
      low: +low.toFixed(2), close: +close.toFixed(2),
      volume: Math.round(1e6 + r() * 8e6),
    });
  }
  return out;
}

export type Index = { name: string; value: number; changePct: number; series: number[] };

export type NewsItem = {
  // Stable across refreshes: derived from the article URL, not the array index.
  // The Alerts page persists "already seen" against this, so an index-based id
  // would re-raise every alert the moment the feed reorders.
  id: string; headline: string; source: string; credibility?: number;
  sentiment: "positive" | "negative" | "neutral"; time: string;
  summary: string; tickers: string[]; category: string;
  // Publisher URL. The backend has always carried a real, grounded link
  // (services/market_news.py drops any item whose URL it didn't actually see
  // in the search results) — the UI just never surfaced it.
  url?: string;
  region: "india" | "global";
  // Curator's judgement. "high" is what the Alerts page raises a notification
  // for; un-curated fallback items are always "low".
  impact: "high" | "medium" | "low";
};

// Session-aware AI briefing that ships with the news payload.
export type NewsBriefing = {
  headline: string; points: string[]; watch: string[];
  phase: SessionPhase;
};

export type SessionPhase = "pre_open" | "open" | "post_close";

export type Holding = { symbol: string; qty: number; avg: number; };

export type EconEvent = {
  date: string; time: string; title: string; country: string; detail?: string;
  impact: "high" | "medium" | "low"; actual?: string; forecast?: string; prior?: string;
  url?: string;
};

export type Alert = {
  id: string; symbol: string; type: "price" | "volume" | "ai" | "news" | "technical";
  condition: string; status: "active" | "triggered" | "paused"; created: string;
};
