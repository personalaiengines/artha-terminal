import { NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE } from "@/middleware";

const API = process.env.ARTHA_API_URL ?? "http://localhost:8000";

/**
 * Ends the session at both ends.
 *
 * Clearing the cookie alone would leave a live token on the server that anyone
 * holding a copy could keep using. The server-side delete is the part that
 * actually revokes; the cookie clear is housekeeping.
 */
export async function POST(req: NextRequest) {
  const token = req.cookies.get(SESSION_COOKIE)?.value;

  if (token) {
    try {
      await fetch(`${API}/api/auth/logout`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        cache: "no-store",
      });
    } catch {
      // The cookie still gets cleared below. A user who clicked sign-out must
      // end up signed out of this browser even if the API is unreachable.
    }
  }

  const res = NextResponse.json({ ok: true });
  res.cookies.set({ name: SESSION_COOKIE, value: "", path: "/", maxAge: 0 });
  return res;
}
