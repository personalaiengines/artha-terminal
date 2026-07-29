import { NextResponse } from "next/server";
import { fromApi } from "@/lib/api-server";

// Global markets board — world indices + commodities with live status.
export async function GET() {
  const g = await fromApi<any>("/api/global", 20000);
  if (!g?.indices) return NextResponse.json({ ok: false });
  const norm = (arr: any[] = []) => arr.map((r) => ({
    name: r.name, symbol: r.symbol, unit: r.unit ?? null,
    price: r.price ?? null, changePct: r.change_pct ?? null,
    // market_status() answers {state: "open"|"closed", note}, not a boolean.
    open: r.status?.state ? r.status.state === "open" : null,
    note: r.status?.note ?? null,
  }));
  return NextResponse.json({ ok: true, indices: norm(g.indices), commodities: norm(g.commodities) });
}
