import { NextResponse } from "next/server";
import { fromApi } from "@/lib/api-server";

// Recorded F&O P&L history. Read from ARTHA's own record, not the broker, so it
// keeps answering after the daily Upstox token expires. No mock: an empty
// record is an honest "nothing recorded yet", never a drawn curve.
export async function GET(req: Request) {
  const q = new URL(req.url).searchParams;
  const range = ["from", "to"]
    .map((k) => [k, q.get(k)] as const)
    .filter(([, v]) => v)
    .map(([k, v]) => `${k}=${encodeURIComponent(v as string)}`)
    .join("&");
  const r = await fromApi<any>(`/api/fno/pnl${range ? `?${range}` : ""}`, 8000);
  if (!r) return NextResponse.json({ ok: false, days: [], contracts: [], months: [], stats: null });
  return NextResponse.json(r);
}
