import { NextResponse } from "next/server";
import { fromApi } from "@/lib/api-server";

// Indian index board (Nifty / Sensex / Bank Nifty / Midcap / VIX + Gift Nifty)
// with per-index session state. The dashboard ticker and index strip poll this.
export const dynamic = "force-dynamic";

export async function GET() {
  const live = await fromApi<{ indices: any[] }>("/api/indices", 8000);
  if (!live?.indices?.length) return NextResponse.json({ ok: false, indices: [] });

  const indices = live.indices.map((i) => ({
    key: i.key,
    name: i.name,
    price: i.price ?? null,
    changePct: i.change_pct ?? null,
    state: i.status?.state ?? "closed",
    note: i.status?.note ?? "",
    localTime: i.status?.local_time ?? "",
  }));
  return NextResponse.json({ ok: true, indices });
}
