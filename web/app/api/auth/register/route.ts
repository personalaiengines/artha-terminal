import { NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE } from "@/middleware";

const API = process.env.ARTHA_API_URL ?? "http://localhost:8000";

/**
 * Creates the account, stores any API keys the user supplied, and signs them in
 * straight away so registration does not end at a second login form.
 *
 * Keys travel once, here, and are encrypted server-side. They are never echoed
 * back — the response carries only `ok`.
 */
export async function POST(req: NextRequest) {
  let body: { email?: string; password?: string; keys?: Record<string, string> };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ ok: false, error: "Malformed request." }, { status: 400 });
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${API}/api/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: body.email,
        password: body.password,
        keys: body.keys ?? {},
      }),
      cache: "no-store",
    });
  } catch {
    return NextResponse.json(
      { ok: false, error: "Could not reach the terminal API." },
      { status: 502 },
    );
  }

  const data = await upstream.json().catch(() => null);
  if (!upstream.ok || !data?.ok) {
    return NextResponse.json(
      { ok: false, error: data?.error ?? "Could not create the account." },
      { status: upstream.status === 200 ? 400 : upstream.status },
    );
  }

  const res = NextResponse.json({ ok: true });
  if (data.token) {
    res.cookies.set({
      name: SESSION_COOKIE,
      value: data.token,
      httpOnly: true,
      sameSite: "lax",
      secure: process.env.NODE_ENV === "production",
      path: "/",
    });
  }
  return res;
}
