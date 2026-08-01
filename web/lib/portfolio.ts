import { Stock, blankStock } from "./data";

// Real portfolio math over live Upstox holdings (from /api/holdings). Each row
// is joined to the live universe by symbol for sector/health; unknown symbols
// get a blank (0/neutral) stock so nothing is fabricated.

export type RawHolding = {
  symbol: string; name: string; qty: number; avg: number; price: number;
  invested: number; current: number; pnl: number; pnlPct: number;
  dayChange?: number | null; dayChangePct?: number | null; prevClose?: number | null;
};

export type PfRow = RawHolding & { stock: Stock; dayPnl: number };

export function portfolioRows(holdings: RawHolding[], universe: Stock[] = []): PfRow[] {
  const uni = new Map(universe.map((s) => [s.symbol, s]));
  return holdings.map((h) => {
    const stock = uni.get(h.symbol) ?? blankStock({ symbol: h.symbol, name: h.name, price: h.price });
    // Day P&L comes from the broker's own last_price vs previous close for THIS
    // holding. It used to read stock.change off the universe row instead, which
    // is a different (often stale, sometimes missing) snapshot — that's how a
    // -1236 day printed as +162. Universe is only a fallback for symbols the
    // broker didn't price; unknown contributes 0 rather than NaN.
    const perShare = h.dayChange ?? stock.change ?? 0;
    return { ...h, stock, dayPnl: perShare * h.qty };
  });
}

export function portfolioSummary(holdings: RawHolding[], universe: Stock[] = []) {
  const rows = portfolioRows(holdings, universe);
  const invested = rows.reduce((a, r) => a + r.invested, 0);
  const current = rows.reduce((a, r) => a + r.current, 0);
  const dayPnl = rows.reduce((a, r) => a + r.dayPnl, 0);
  const pnl = current - invested;
  // Value-weighted health over only the holdings that actually have a health
  // score. Counting an unscored holding as 0 would drag the portfolio number
  // down and misreport it as a real risk signal.
  const scored = rows.filter((r) => typeof r.stock.health === "number");
  const scoredValue = scored.reduce((a, r) => a + r.current, 0);
  const health = scoredValue
    ? Math.round(scored.reduce((a, r) => a + (r.stock.health as number) * r.current, 0) / scoredValue)
    : null;
  return {
    rows, invested, current, dayPnl,
    dayPnlPct: current - dayPnl ? (dayPnl / (current - dayPnl)) * 100 : 0,
    pnl, pnlPct: invested ? (pnl / invested) * 100 : 0, health,
  };
}

// Portfolio quality read-outs. These were hardcoded strings in the UI
// ("Diversification: Good", "Concentration: Moderate", "Quality: High") that
// never changed regardless of what was actually held — pure fabrication on a
// page about the user's real money. Computed from the holdings now, and null
// when the inputs to judge it don't exist.
export function portfolioQuality(holdings: RawHolding[], universe: Stock[] = []) {
  const rows = portfolioRows(holdings, universe);
  const total = rows.reduce((a, r) => a + r.current, 0);
  if (!rows.length || !total) return null;

  const sectors = new Set(rows.map((r) => r.stock.sector).filter((s) => s && s !== "—" && s !== "Other"));
  const diversification = rows.length >= 15 && sectors.size >= 6 ? "Good"
    : rows.length >= 8 && sectors.size >= 4 ? "Moderate" : "Low";

  // Weight of the single largest position — the standard concentration read.
  const topWeight = Math.max(...rows.map((r) => r.current)) / total * 100;
  const concentration = topWeight >= 35 ? "High" : topWeight >= 20 ? "Moderate" : "Low";

  const scored = rows.filter((r) => typeof r.stock.health === "number");
  const scoredValue = scored.reduce((a, r) => a + r.current, 0);
  const avgHealth = scoredValue
    ? scored.reduce((a, r) => a + (r.stock.health as number) * r.current, 0) / scoredValue
    : null;
  const quality = avgHealth == null ? null : avgHealth >= 70 ? "High" : avgHealth >= 45 ? "Moderate" : "Low";

  return {
    diversification, concentration, quality,
    topWeight, sectorCount: sectors.size, holdingCount: rows.length,
  };
}

export function sectorAllocation(holdings: RawHolding[], universe: Stock[] = []) {
  const rows = portfolioRows(holdings, universe);
  const total = rows.reduce((a, r) => a + r.current, 0);
  if (!total) return [];
  const map = new Map<string, number>();
  rows.forEach((r) => map.set(r.stock.sector, (map.get(r.stock.sector) ?? 0) + r.current));
  const palette = ["#3b82f6", "#8b5cf6", "#10b981", "#f5a623", "#f4586a", "#38bdf8", "#a78bfa"];
  return [...map.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([name, v], i) => ({ name, value: (v / total) * 100, color: palette[i % palette.length] }));
}

export function moversFrom(stocks: Stock[] = []) {
  // Only rank symbols that actually have the metric — a stock with no price
  // data must never surface as a "top gainer" by sorting as 0.
  const withChange = stocks.filter((s) => typeof s.changePct === "number");
  const withVolume = stocks.filter((s) => typeof s.volume === "number");
  return {
    gainers: [...withChange].sort((a, b) => b.changePct! - a.changePct!).slice(0, 5),
    losers: [...withChange].sort((a, b) => a.changePct! - b.changePct!).slice(0, 5),
    volume: [...withVolume].sort((a, b) => b.volume! - a.volume!).slice(0, 5),
  };
}
