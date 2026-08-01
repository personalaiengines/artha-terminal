import { NextResponse } from "next/server";
import { fromApi } from "@/lib/api-server";

// IV term structure: ATM IV per expiry across the nearest `cap` expiries.
// `cap` is deliberately small (one chain fetch per expiry) — render it, so the
// curve is never read as the full expiry board. `unpriced` lists expiries whose
// ATM legs carried no live IV; they are absent from `points`, never drawn as 0.
export async function GET(_req: Request, { params }: { params: Promise<{ index: string }> }) {
  const { index } = await params;
  const r = await fromApi<any>(`/api/fno/${index.toUpperCase()}/term`, 15000);
  if (!r) return NextResponse.json({ ok: false, points: [], unpriced: [], complete: false });
  return NextResponse.json(r);
}
