import { NextRequest, NextResponse } from "next/server";
import { cookies } from "next/headers";
import { SESSION_COOKIE } from "@/middleware";

const API = process.env.ARTHA_API_URL ?? "http://localhost:8000";

/** Removes one stored credential. Falls back to the server's own .env value
 * if one exists — the same fallback auth.resolve_key already applies. */
export async function DELETE(
  req: NextRequest,
  { params }: { params: Promise<{ provider: string }> },
) {
  const { provider } = await params;
  const token = (await cookies()).get(SESSION_COOKIE)?.value;

  try {
    const upstream = await fetch(`${API}/api/auth/keys/${encodeURIComponent(provider)}`, {
      method: "DELETE",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
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
