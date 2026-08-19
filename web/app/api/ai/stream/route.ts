import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { SESSION_COOKIE } from "@/middleware";

// SSE passthrough to the Python agent's streaming chat.
//
// Deliberately NOT using lib/api-server's sendApi — that buffers the whole JSON
// body, which is the opposite of what this route is for. We pipe the upstream
// byte stream straight through so tokens reach the browser as they're produced.
export const dynamic = "force-dynamic";

const API = process.env.ARTHA_API_URL ?? "http://localhost:8000";

export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}));
  const q = (body?.q ?? "").toString().trim();
  if (!q) return NextResponse.json({ ok: false, error: "empty query" }, { status: 400 });

  const token = (await cookies()).get(SESSION_COOKIE)?.value;

  let upstream: Response;
  try {
    upstream = await fetch(`${API}/api/ai/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ q, history: body?.history ?? [] }),
      // The agent can legitimately run for minutes on a deep dive.
      signal: AbortSignal.timeout(300000),
    });
  } catch {
    return NextResponse.json({ ok: false, error: "api unreachable" }, { status: 502 });
  }

  if (!upstream.ok || !upstream.body) {
    return NextResponse.json({ ok: false, error: `api ${upstream.status}` }, { status: 502 });
  }

  return new Response(upstream.body, {
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      "X-Accel-Buffering": "no",
      Connection: "keep-alive",
    },
  });
}
