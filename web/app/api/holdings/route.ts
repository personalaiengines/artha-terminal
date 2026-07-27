import { NextResponse } from "next/server";

// Real Upstox holdings. No mock: passes through ok:false + status
// (expired/missing) so the UI can prompt re-authorization rather than faking
// positions. Direct fetch (not fromApi) to preserve the ok:false status.
const BASE = process.env.ARTHA_API_URL ?? "http://localhost:8000";

export async function GET() {
  try {
    const res = await fetch(`${BASE}/api/holdings`, { cache: "no-store" });
    return NextResponse.json(await res.json());
  } catch {
    return NextResponse.json({ ok: false, status: "error", items: [] });
  }
}
