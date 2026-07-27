import { NextResponse } from "next/server";
import { sendApi } from "@/lib/api-server";

// Real AI analyst: forwards the question to the Python agent (grounded per-stock
// analysis when a symbol is detected, else free-form LLM). Returns ok:false on
// failure/missing keys → the page uses its scripted demo answer.
export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}));
  const q = (body?.q ?? "").toString().trim();
  if (!q) return NextResponse.json({ ok: false, error: "empty query" });
  const res = await sendApi<any>("/api/ai", "POST", { q }, 45000);
  if (!res || res.ok === false || !res.answer) return NextResponse.json({ ok: false });
  return NextResponse.json({
    ok: true,
    answer: res.answer,
    symbol: res.symbol ?? null,
    cards: res.cards ?? (res.symbol ? [res.symbol] : []),
    sources: (res.tools ?? []).length ? res.tools : ["ARTHA Agent", "Screener.in", "Upstox"],
    model: res.model ?? null,
  });
}
