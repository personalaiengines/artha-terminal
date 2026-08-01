import { NextResponse } from "next/server";
import { sendApi } from "@/lib/api-server";

// Real AI analyst: forwards the question to the Python agent (grounded per-stock
// analysis when a symbol is detected, else free-form LLM). Returns ok:false on
// failure/missing keys → the page uses its scripted demo answer.
//
// Symbol-detected queries run the FULL agent tool-use loop
// (agent/orchestration.py, up to 15 iterations of real tool calls) plus the
// Bull/Bear/Judge debate layer on deep_dive/verdict analyses (agent/debate.py)
// — heavier than /api/stock/[symbol]/analysis or /api/fno/[index]/narrative,
// which are one-shot LLM calls over a precomputed snapshot and only need
// their 95s timeout. Measured end-to-end: the combined tool-loop + debate
// path can run 100-140s. 45s (and even 95s) cut this off after the Python
// side had already produced a real answer.
export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}));
  const q = (body?.q ?? "").toString().trim();
  if (!q) return NextResponse.json({ ok: false, error: "empty query" });
  const res = await sendApi<any>("/api/ai", "POST", { q }, 170000);
  if (!res || res.ok === false || !res.answer) {
    // Pass the reason through. This used to collapse every failure to a bare
    // {ok:false}, which the page renders as its scripted demo answer — so a real
    // outage, an over-length question and a model returning nothing were all
    // indistinguishable from a genuine reply. The Python side now sends
    // error/detail (e.g. "empty_answer"); surface it.
    return NextResponse.json({
      ok: false,
      error: res?.error ?? "unavailable",
      detail: res?.detail ?? null,
    });
  }
  return NextResponse.json({
    ok: true,
    answer: res.answer,
    symbol: res.symbol ?? null,
    cards: res.cards ?? (res.symbol ? [res.symbol] : []),
    // Only the tools actually used. The fallback here used to be a hard-coded
    // ["ARTHA Agent", "Screener.in", "Upstox"] whenever the agent reported no
    // tools — inventing provenance for an answer, and claiming two data vendors
    // that were never consulted. That is precisely what GROUNDING forbids of the
    // model, so the UI must not do it either. No tools used, no sources shown.
    sources: res.tools ?? [],
    model: res.model ?? null,
  });
}
