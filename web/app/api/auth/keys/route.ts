import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";
import { SESSION_COOKIE } from "@/middleware";

const API = process.env.ARTHA_API_URL ?? "http://localhost:8000";

/** Saves one credential for the signed-in user. Gated — middleware already
 * refused this request without a cookie, this attaches it for the Python API. */
export async function POST(req: NextRequest) {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  let body: { provider?: string; key?: string };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ ok: false, error: "Malformed request." }, { status: 400 });
  }

  try {
    const upstream = await fetch(`${API}/api/auth/keys`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ provider: body.provider, key: body.key }),
      cache: "no-store",
    });
    const data = await upstream.json().catch(() => null);
    return NextResponse.json(data ?? { ok: false, error: "No response from the API." },
                             { status: upstream.status });
  } catch {
    return NextResponse.json(
      { ok: false, error: "Could not reach the terminal API." },
      { status: 502 },
    );
  }
}
