import { NextResponse } from "next/server";
import { fromApi } from "@/lib/api-server";

// Real F&O game plan (Upstox option chain + analysis) mapped to the UI shape.
// Returns ok:false when Upstox is unreachable / outside market hours → the page
// keeps its mock chain.
export async function GET(req: Request, { params }: { params: Promise<{ index: string }> }) {
  const { index } = await params;
  // ?expiry=YYYY-MM-DD selects a listed non-nearest expiry. Forwarded encoded;
  // the Python side validates it against the listed set and 400s on junk.
  const expiry = new URL(req.url).searchParams.get("expiry");
  const q = expiry ? `?expiry=${encodeURIComponent(expiry)}` : "";
  const p = await fromApi<any>(`/api/fno/${index.toUpperCase()}${q}`, 20000);
  if (!p || p.ok === false || !p.strikes?.length) return NextResponse.json({ ok: false });

  // iv, delta and buildup pass through as null when absent — a leg Upstox never
  // priced must not arrive as 0, which reads like a measurement. (`iv ?? 0` was
  // the last of these; the parser's zero-guard was being undone right here.)
  const leg = (l: any) => ({
    oi: l?.oi ?? 0, oiChg: l?.oi_change ?? 0, vol: l?.volume ?? 0,
    iv: l?.iv ?? null, ltp: l?.ltp ?? 0,
    delta: l?.delta ?? null, buildup: l?.buildup ?? null,
  });
  const rows = p.strikes.map((s: any) => ({
    strike: s.strike, call: leg(s.call), put: leg(s.put),
  }));
  return NextResponse.json({
    ok: true,
    index: p.index, name: p.name, spot: p.spot, atm: p.atm,
    pcr: p.pcr_oi, maxPain: p.max_pain, iv: p.atm_iv, vix: p.india_vix,
    vixPctile: p.vix_percentile ?? null, vixWindow: p.vix_window ?? 0,
    vixAsOf: p.vix_as_of ?? null,
    callWall: p.oi_walls?.call_wall, putWall: p.oi_walls?.put_wall,
    biasLabel: p.bias?.label, biasScore: p.bias?.score,
    strategy: p.strategy?.name, strategyNote: p.strategy?.note,
    // Structural description of the named concept: anchor strikes plus the legs
    // that reference them. /options prices each leg off the real chain — never
    // an assumed premium — and draws nothing when a leg will not resolve.
    strategyAnchors: p.strategy?.anchors ?? null, strategyLegs: p.strategy?.legs ?? [],
    expiry: p.expiry, expiries: p.expiries ?? [],
    // `crossed` marks a level price has flipped side; zones/structure are the
    // confluence engine's output. All three render as-is — do not reshape.
    levels: (p.levels ?? []).map((l: any) => ({
      label: l.label, price: l.price, kind: l.kind, crossed: l.crossed ?? false,
    })),
    zones: p.zones ?? [],
    structure: p.structure ?? null,
    buildupSummary: p.buildup_summary ?? null,
    buildupBasis: p.buildup_basis ?? null,
    deltaOi: p.delta_oi ?? null,
    rows,
  });
}
