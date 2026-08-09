import { NextResponse } from "next/server";
import { sendApi } from "@/lib/api-server";

// Rebuild the P&L record from Upstox trade history. POST because it writes;
// sendApi (not fromApi) so an ok:false — expired token, no trades — reaches the
// UI with its reason instead of collapsing to null.
export async function POST() {
  const r = await sendApi<any>("/api/fno/pnl/backfill", "POST", undefined, 120000);
  return NextResponse.json(r ?? { ok: false, message: "Could not reach the API." });
}
