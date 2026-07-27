import { NextResponse } from "next/server";
import { fromApi, sendApi } from "@/lib/api-server";

// GET: real saved alerts (empty when none). POST: create a real alert.
export async function GET() {
  const r = await fromApi<{ items: any[] }>("/api/alerts", 6000);
  if (!r?.items) return NextResponse.json({ ok: false, items: [] });
  const items = r.items.map((a) => ({
    id: String(a.id), symbol: a.symbol, type: a.type,
    condition: a.condition, status: a.status, created: a.created,
  }));
  return NextResponse.json({ ok: true, items });
}

export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}));
  const res = await sendApi<any>("/api/alerts", "POST", body, 8000);
  if (!res || res.ok === false) return NextResponse.json({ ok: false, error: res?.error ?? "failed" }, { status: 400 });
  return NextResponse.json({ ok: true, id: res.id });
}
