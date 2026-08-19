import { NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE } from "@/middleware";

const API = process.env.ARTHA_API_URL ?? "http://localhost:8000";

/**
 * Exchanges email + password for a session token and stores it in an httpOnly
 * cookie.
 *
 * The token is never returned to the browser in the response body. If it were,
 * any script on the page could read it and it would stop being httpOnly in any
 * meaningful sense — the cookie flag only helps if the value has no second home.
 */
export async function POST(req: NextRequest) {
  let body: { email?: string; password?: string; remember?: boolean };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ ok: false, error: "Malformed request." }, { status: 400 });
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${API}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: body.email,
        password: body.password,
        remember: Boolean(body.remember),
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
  if (!upstream.ok || !data?.ok || !data?.token) {
    // Pass the upstream status through so a rate-limited login stays a 429
    // rather than being flattened into a generic failure.
    return NextResponse.json(
      { ok: false, error: data?.error ?? "Email or password is incorrect." },
      { status: upstream.status === 200 ? 401 : upstream.status },
    );
  }

  const res = NextResponse.json({ ok: true });
  res.cookies.set({
    name: SESSION_COOKIE,
    value: data.token,
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    // "Remember me" is the only thing that makes this a persistent cookie.
    // Without it there is no maxAge, so the cookie dies with the browser
    // session and the server-side row expires on its own 12h clock.
    ...(body.remember ? { maxAge: 60 * 60 * 24 * 30 } : {}),
  });
  return res;
}
