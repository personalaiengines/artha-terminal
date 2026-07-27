import { NextResponse } from "next/server";
import { fromApi } from "@/lib/api-server";

// AI-generated, live-grounded market brief for the dashboard. ok:false when the
// LLM/snapshot is unavailable → the page keeps its deterministic fallback line.
export async function GET() {
  const b = await fromApi<{ ok: boolean; brief: string; sources: string[] }>("/api/brief", 30000);
  if (!b?.brief) return NextResponse.json({ ok: false });
  return NextResponse.json({ ok: true, brief: b.brief, sources: b.sources ?? [] });
}
