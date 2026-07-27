import { NextResponse } from "next/server";
import { sendApi } from "@/lib/api-server";

// Exchange a pasted Upstox OAuth code (or full redirect URL) for a fresh token.
export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}));
  const res = await sendApi<any>("/api/upstox/token", "POST", { code: body?.code ?? "" }, 20000);
  if (!res) return NextResponse.json({ ok: false, message: "API unreachable" });
  return NextResponse.json(res);
}
