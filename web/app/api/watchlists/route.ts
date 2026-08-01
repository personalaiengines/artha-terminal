import { NextResponse } from "next/server";
import { fromApi, sendApi } from "@/lib/api-server";

// GET: real saved watchlists (empty when none created yet). POST: create a list.
export async function GET() {
  const r = await fromApi<{ items: any[] }>("/api/watchlists", 6000);
  if (!r?.items) return NextResponse.json({ ok: false, items: [] });
  return NextResponse.json({ ok: true, items: r.items });
}

export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}));
  const res = await sendApi<any>("/api/watchlists", "POST", body, 8000);
  if (!res || res.ok === false) return NextResponse.json({ ok: false, error: res?.error ?? "failed" }, { status: 400 });
  return NextResponse.json({ ok: true, id: res.id, name: res.name });
}
