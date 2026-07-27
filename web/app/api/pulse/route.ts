import { NextResponse } from "next/server";
import { fromApi } from "@/lib/api-server";

// Live market breadth + sector rotation from services/breadth.py. Shape kept
// small and explicit; the Markets page consumes sectors[] and breadth{}.
export async function GET() {
  const live = await fromApi<any>("/api/pulse", 12000);
  if (!live?.sectors) return NextResponse.json({ ok: false });
  return NextResponse.json({
    ok: true,
    breadth: live.breadth ?? null,
    mood: live.mood ?? null,
    sectors: (live.sectors ?? []).map((s: any) => ({ name: s.sector, chg: s.avg_chg, count: s.total })),
    indices: (live.indices ?? []).map((i: any) => ({ name: i.name, value: i.value, change: i.change })),
  });
}
