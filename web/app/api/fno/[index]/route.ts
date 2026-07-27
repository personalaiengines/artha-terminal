import { NextResponse } from "next/server";
import { fromApi } from "@/lib/api-server";

// Real F&O game plan (Upstox option chain + analysis) mapped to the UI shape.
// Returns ok:false when Upstox is unreachable / outside market hours → the page
// keeps its mock chain.
export async function GET(_req: Request, { params }: { params: Promise<{ index: string }> }) {
  const { index } = await params;
  const p = await fromApi<any>(`/api/fno/${index.toUpperCase()}`, 20000);
  if (!p || p.ok === false || !p.strikes?.length) return NextResponse.json({ ok: false });

  const rows = p.strikes.map((s: any) => ({
    strike: s.strike,
    call: { oi: s.call?.oi ?? 0, oiChg: s.call?.oi_change ?? 0, vol: s.call?.volume ?? 0, iv: s.call?.iv ?? 0, ltp: s.call?.ltp ?? 0 },
    put: { oi: s.put?.oi ?? 0, oiChg: s.put?.oi_change ?? 0, vol: s.put?.volume ?? 0, iv: s.put?.iv ?? 0, ltp: s.put?.ltp ?? 0 },
  }));
  return NextResponse.json({
    ok: true,
    index: p.index, name: p.name, spot: p.spot, atm: p.atm,
    pcr: p.pcr_oi, maxPain: p.max_pain, iv: p.atm_iv, vix: p.india_vix,
    callWall: p.oi_walls?.call_wall, putWall: p.oi_walls?.put_wall,
    biasLabel: p.bias?.label, biasScore: p.bias?.score,
    strategy: p.strategy?.name, strategyNote: p.strategy?.note,
    expiry: p.expiry,
    levels: (p.levels ?? []).map((l: any) => ({ label: l.label, price: l.price, kind: l.kind })),
    rows,
  });
}
