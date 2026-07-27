import { NextResponse } from "next/server";
import { fromApi } from "@/lib/api-server";

// Aggregate system health for the global banner (Upstox auth, LLM keys, DB).
export async function GET() {
  const s = await fromApi<any>("/api/system/status", 15000);
  if (!s) return NextResponse.json({ ok: false });
  return NextResponse.json({
    ok: true,
    upstox: {
      status: s.upstox?.status ?? "unknown", // ok | expired | missing | error
      name: s.upstox?.name ?? null,
      loginUrl: s.upstox?.login_url ?? null,
      savedAt: s.upstox?.saved_at ?? null,
    },
    llm: s.llm ?? { openrouter: false, nvidia: false },
    dbSymbols: s.db_symbols ?? 0,
  });
}
