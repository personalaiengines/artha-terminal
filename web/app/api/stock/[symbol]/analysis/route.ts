import { NextResponse } from "next/server";
import { fromApi } from "@/lib/api-server";

// Grounded NIM narrative for one stock (real snapshot facts, LLM interprets
// only). Slow (up to ~90s cold) — give it a long timeout; no mock text.
export async function GET(_req: Request, { params }: { params: Promise<{ symbol: string }> }) {
  const { symbol } = await params;
  const live = await fromApi<{ ok: boolean; markdown?: string; model?: string; error?: string }>(
    `/api/stock/${symbol.toUpperCase()}/analysis`, 95000
  );
  if (!live?.ok) return NextResponse.json({ ok: false, markdown: null });
  return NextResponse.json(live);
}
