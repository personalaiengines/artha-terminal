import { NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE } from "@/middleware";

const API = process.env.ARTHA_API_URL ?? "http://localhost:8000";

/** Who is signed in. Used by the shell to show the account and to detect an expired session. */
export async function GET(req: NextRequest) {
  const token = req.cookies.get(SESSION_COOKIE)?.value;
  if (!token) return NextResponse.json({ ok: false }, { status: 401 });

  try {
    const upstream = await fetch(`${API}/api/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    });
    const data = await upstream.json().catch(() => null);
    return NextResponse.json(data ?? { ok: false }, { status: upstream.status });
  } catch {
    return NextResponse.json({ ok: false, error: "API unreachable" }, { status: 502 });
  }
}
