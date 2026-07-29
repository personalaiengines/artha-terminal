import { NextResponse } from "next/server";
import { sendApi } from "@/lib/api-server";

export async function DELETE(_req: Request, { params }: { params: Promise<{ id: string; symbol: string }> }) {
  const { id, symbol } = await params;
  const res = await sendApi<any>(`/api/watchlists/${id}/items/${symbol}`, "DELETE", undefined, 8000);
  if (!res || res.ok === false) return NextResponse.json({ ok: false }, { status: 400 });
  return NextResponse.json({ ok: true });
}
