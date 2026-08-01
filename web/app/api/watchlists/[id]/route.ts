import { NextResponse } from "next/server";
import { sendApi } from "@/lib/api-server";

export async function DELETE(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const res = await sendApi<any>(`/api/watchlists/${id}`, "DELETE", undefined, 8000);
  if (!res || res.ok === false) return NextResponse.json({ ok: false }, { status: 400 });
  return NextResponse.json({ ok: true });
}
