import { NextResponse } from "next/server";
import { fromApi } from "@/lib/api-server";

// Live equity universe (DB-backed). No mock: empty + ok:false when the API has
// no data, so the UI shows an honest empty state instead of fabricated rows.
export async function GET() {
  const live = await fromApi<{ items: unknown[] }>("/api/universe");
  if (!live?.items?.length) return NextResponse.json({ ok: false, items: [] });
  return NextResponse.json({ ok: true, items: live.items });
}
