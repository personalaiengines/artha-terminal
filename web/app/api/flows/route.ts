import { NextResponse } from "next/server";
import { fromApi } from "@/lib/api-server";

// FII/DII institutional flows (NSE). Net figures in ₹ Cr + stance labels.
export async function GET() {
  const f = await fromApi<any>("/api/flows", 20000);
  if (!f) return NextResponse.json({ ok: false });
  return NextResponse.json({
    ok: true,
    date: f.date ?? null,
    fiiNet: f.fii?.net ?? null,
    diiNet: f.dii?.net ?? null,
    fiiStance: f.fii_stance ?? null,
    diiStance: f.dii_stance ?? null,
    stale: f.stale ?? false,
  });
}
