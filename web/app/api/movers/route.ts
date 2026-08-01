import { NextResponse } from "next/server";
import { fromApi } from "@/lib/api-server";
import { blankStock } from "@/lib/data";

// Market-wide top movers (NSE/yfinance). Each row is shaped into a Stock from
// the real fields only (name/fundamentals stay blank — no mock) so StockRow renders.
function toStocks(arr: any[] = [], key: "pct" | "volume") {
  return arr.map((r) => blankStock({
    symbol: (r.symbol || "").toUpperCase(),
    name: r.name ?? undefined,
    price: r.price ?? undefined,
    changePct: r.pct ?? undefined,
    // Source only gives price + %; derive the absolute ₹ change the same way
    // the backend does for the main universe, so the ₹/% toggle works here too.
    change: r.price != null && r.pct != null ? (r.price * r.pct) / 100 : undefined,
    volume: key === "volume" ? (r.volume ?? undefined) : undefined,
  }));
}

export async function GET() {
  const m = await fromApi<any>("/api/movers", 20000);
  if (!m?.ok && !m?.gainers) return NextResponse.json({ ok: false });

  // Per-index / per-sector slices (NIFTY 50, Bank Nifty, Sensex, IT, Pharma …),
  // cut server-side from the same priced universe.
  const groups: Record<string, { gainers: any[]; losers: any[]; count: number }> = {};
  for (const [name, g] of Object.entries<any>(m.groups ?? {})) {
    groups[name] = {
      gainers: toStocks(g.gainers, "pct"),
      losers: toStocks(g.losers, "pct"),
      count: g.count ?? 0,
    };
  }

  return NextResponse.json({
    ok: true,
    gainers: toStocks(m.gainers, "pct"),
    losers: toStocks(m.losers, "pct"),
    volume: toStocks(m.volume, "volume"),
    groups,
    source: m.source ?? null,
  });
}
