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
    volume: key === "volume" ? (r.volume ?? undefined) : undefined,
  }));
}

export async function GET() {
  const m = await fromApi<any>("/api/movers", 20000);
  if (!m?.ok && !m?.gainers) return NextResponse.json({ ok: false });
  return NextResponse.json({
    ok: true,
    gainers: toStocks(m.gainers, "pct"),
    losers: toStocks(m.losers, "pct"),
    volume: toStocks(m.volume, "volume"),
    source: m.source ?? null,
  });
}
