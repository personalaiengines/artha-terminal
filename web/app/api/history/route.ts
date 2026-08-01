import { NextResponse } from "next/server";
import { fromApi } from "@/lib/api-server";

// Real trailing closes per symbol, for sparklines. Replaces lib/data.ts::series(),
// a seeded random walk that made every sparkline a fixed function of the symbol
// name — visually plausible, but it never changed and never reflected the market.
export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const symbols = searchParams.get("symbols") ?? "";
  const days = searchParams.get("days") ?? "30";
  const ohlc = searchParams.get("ohlc");
  if (!symbols) return NextResponse.json({ ok: true, series: {} });
  const q = `symbols=${encodeURIComponent(symbols)}&days=${encodeURIComponent(days)}${ohlc ? "&ohlc=1" : ""}`;
  const r = await fromApi<any>(`/api/history?${q}`, 10000);
  if (!r) return NextResponse.json({ ok: false, series: {}, candles: [] });
  if (ohlc) return NextResponse.json({ ok: true, candles: r.candles ?? [] });
  if (!r.series) return NextResponse.json({ ok: false, series: {} });
  return NextResponse.json({ ok: true, series: r.series });
}
