import { NextResponse } from "next/server";
import { fromApi } from "@/lib/api-server";

// The /fno AI surface: where open interest moved this session and what that says
// about the writers' defence. Slow (up to ~90s cold) — no mock text on failure.
export async function GET(_req: Request, { params }: { params: Promise<{ index: string }> }) {
  const { index } = await params;
  const live = await fromApi<{ ok: boolean; markdown?: string; model?: string }>(
    `/api/fno/${index.toUpperCase()}/oi-read`, 95000
  );
  if (!live?.ok) return NextResponse.json({ ok: false, markdown: null });
  return NextResponse.json(live);
}
