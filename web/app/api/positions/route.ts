import { NextResponse } from "next/server";
import { fromApi } from "@/lib/api-server";

// The user's live F&O positions, READ-ONLY. GET only — there is no order path
// here or behind it. No mock: an expired/missing token comes back as ok:false
// with an empty book so the UI prompts re-authorization (the banner reads the
// reason from /api/system/status). An empty book with a valid token is ok:true
// and items: [] — a real "no open positions", not an error.
export async function GET() {
  const r = await fromApi<any>("/api/positions", 10000, true);
  if (!r) return NextResponse.json({ ok: false, status: "error", items: [] });
  return NextResponse.json(r);
}
