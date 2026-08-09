import { NextResponse } from "next/server";
import { fromApi } from "@/lib/api-server";

// Real Upstox holdings. No mock: an expired/missing token comes back as
// ok:false with an empty book so the UI prompts re-authorization (the banner
// reads the reason from /api/system/status) rather than faking positions.
export async function GET() {
  const r = await fromApi<any>("/api/holdings", 10000, true);
  if (!r) return NextResponse.json({ ok: false, status: "error", items: [] });
  return NextResponse.json(r);
}
