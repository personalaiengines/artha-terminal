import { NextRequest, NextResponse } from "next/server";

const API = process.env.ARTHA_API_URL ?? "http://localhost:8000";

/**
 * Validates one API key against its real provider before it is ever stored.
 *
 * Deliberately reachable without a session: it runs during registration, before
 * an account exists. It stores nothing and returns only a verdict, so the worst
 * an unauthenticated caller achieves is testing a key they already hold.
 */
export async function POST(req: NextRequest) {
  let body: { provider?: string; key?: string };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ ok: false, error: "Malformed request." }, { status: 400 });
  }

  try {
    const upstream = await fetch(`${API}/api/auth/test-key`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider: body.provider, key: body.key }),
      cache: "no-store",
    });
    const data = await upstream.json().catch(() => null);
    return NextResponse.json(data ?? { ok: false, error: "No response from the provider." });
  } catch {
    return NextResponse.json(
      { ok: false, error: "Could not reach the terminal API." },
      { status: 502 },
    );
  }
}
