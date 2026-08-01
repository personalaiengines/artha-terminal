import { NextResponse } from "next/server";
import { fromApi } from "@/lib/api-server";

// Proxy for on-demand freshness. Fire-and-forget from the client's point of
// view: it returns as soon as the refresh is queued, never waiting on yfinance.
export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const symbols = searchParams.get("symbols") ?? "";
  if (!symbols) return NextResponse.json({ ok: true, queued: 0 });
  const r = await fromApi<any>(`/api/ensure?symbols=${encodeURIComponent(symbols)}`, 8000);
  return NextResponse.json({ ok: true, queued: r?.queued ?? 0, stale: r?.stale ?? 0 });
}
