import { NextResponse } from "next/server";
import { fromApi } from "@/lib/api-server";

// Every listed expiry for one index (ascending, today or later) plus `default`
// — the one /api/fno/{index} uses when no ?expiry= is given. Passthrough.
export async function GET(_req: Request, { params }: { params: Promise<{ index: string }> }) {
  const { index } = await params;
  const r = await fromApi<any>(`/api/fno/${index.toUpperCase()}/expiries`, 10000);
  if (!r) return NextResponse.json({ ok: false, expiries: [], default: null });
  return NextResponse.json(r);
}
