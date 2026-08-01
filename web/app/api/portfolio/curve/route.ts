import { NextResponse } from "next/server";
import { fromApi } from "@/lib/api-server";

// Real portfolio value series (holdings x historical closes) plus risk metrics
// computed from those actual returns.
export async function GET() {
  const r = await fromApi<any>("/api/portfolio/curve", 15000);
  if (!r) return NextResponse.json({ ok: false, points: [], metrics: {} });
  return NextResponse.json({
    ok: true,
    points: r.points ?? [],
    metrics: r.metrics ?? {},
    covered: r.covered ?? 0,
    total: r.total ?? 0,
  });
}
