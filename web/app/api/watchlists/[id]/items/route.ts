import { NextResponse } from "next/server";
import { sendApi } from "@/lib/api-server";

export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const body = await req.json().catch(() => ({}));
  const res = await sendApi<any>(`/api/watchlists/${id}/items`, "POST", body, 8000);
  if (!res || res.ok === false) return NextResponse.json({ ok: false, error: res?.error ?? "failed" }, { status: 400 });
  return NextResponse.json({ ok: true });
}
