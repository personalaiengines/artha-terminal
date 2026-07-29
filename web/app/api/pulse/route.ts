import { NextResponse } from "next/server";
import { fromApi } from "@/lib/api-server";

// Live market breadth + sector rotation from services/breadth.py.
//
// `stale`/`asOf` come from the API's last-known-good fallback: when the
// upstream can't be reached the previous good snapshot is served with the time
// it was good at, and the UI labels it. Returning ok:false here instead would
// push the page onto a differently-shaped client-side computation, which is
// how the sector heatmap used to change shape whenever a feed hiccuped.
export async function GET() {
  const live = await fromApi<any>("/api/pulse", 12000);
  if (!live?.sectors?.length) {
    return NextResponse.json({ ok: false, stale: true, asOf: null, sectors: [] });
  }
  return NextResponse.json({
    ok: true,
    stale: !!live.stale,
    asOf: live.as_of ?? null,
    breadth: live.breadth ?? null,
    mood: live.mood ?? null,
    // Which universe breadth was measured over — 43 of 49 means nothing
    // without saying 49 of what.
    universeLabel: live.universe_label ?? null,
    topGainer: live.top_gainer ?? null,
    topLoser: live.top_loser ?? null,
    sectors: (live.sectors ?? []).map((s: any) => ({ name: s.sector, chg: s.avg_chg, count: s.total })),
    indices: (live.indices ?? []).map((i: any) => ({ name: i.name, value: i.value, change: i.change })),
  });
}
