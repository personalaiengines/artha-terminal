import { redirect } from "next/navigation";
import { cookies } from "next/headers";
import { AppShell } from "@/components/layout/app-shell";
import { SESSION_COOKIE } from "@/middleware";

const API = process.env.ARTHA_API_URL ?? "http://localhost:8000";

/**
 * The signed-in application. Everything under (portal) renders inside AppShell.
 *
 * Two gates, not one, and they check different things:
 *
 *   `middleware.ts`  — fast, edge-cheap: does a session cookie EXIST. Runs on
 *                      every request including static assets it lets through.
 *   this layout      — slower, correct: is that cookie's token STILL VALID.
 *                      Runs once per navigation, in a Server Component that can
 *                      await a real API call.
 *
 * The two-gate split exists because a cookie can outlive its session — sign out
 * revokes the token server-side but a stale browser cookie survives until it
 * expires or is overwritten. Middleware's presence check alone let a page
 * render its full shell after logout (verified live: /dashboard returned 200
 * on a revoked token). The Python API itself always rejected the token
 * correctly — no real data ever reached the page — but a portal that visibly
 * renders for a logged-out visitor fails "only logged in users can access it"
 * even with empty panels. This closes that gap without slowing down every
 * static asset request through middleware.
 */
export default async function PortalLayout({ children }: { children: React.ReactNode }) {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!token) redirect("/login");

  let valid = false;
  try {
    const res = await fetch(`${API}/api/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
      signal: AbortSignal.timeout(4000),
    });
    valid = res.ok;
  } catch {
    // API unreachable: fail open on the redirect (do not lock the owner out of
    // their own terminal because the backend hiccuped), the page's own data
    // fetches will show the outage. Middleware's cookie-presence check is what
    // already stood between this and a fully open portal.
    valid = true;
  }

  if (!valid) redirect("/login");

  return <AppShell>{children}</AppShell>;
}
