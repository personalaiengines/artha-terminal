import { NextRequest, NextResponse } from "next/server";

export const SESSION_COOKIE = "artha_session";

/**
 * The gate. Default-deny: anything not explicitly listed below requires a
 * session, so a page added later is protected without anyone remembering to
 * add it here. That is the whole reason this is an allowlist and not a
 * "redirect if path starts with /portal" check.
 *
 * Exact paths only — a `startsWith` test would let `/login-as-admin` or
 * `/registerx` through.
 */
const PUBLIC_PATHS = new Set(["/", "/login", "/register"]);

/**
 * Next.js route handlers that must answer before a session exists. Everything
 * else under /api/ is a proxy to the Python API and is gated too — otherwise
 * the browser could read portfolio data through the proxy while logged out,
 * which is exactly the hole the login screen is supposed to close.
 */
const PUBLIC_API = new Set([
  "/api/auth/login",
  "/api/auth/register",
  "/api/auth/logout",
]);

function isPublic(pathname: string): boolean {
  if (PUBLIC_PATHS.has(pathname)) return true;
  if (PUBLIC_API.has(pathname)) return true;
  return false;
}

export function middleware(req: NextRequest) {
  const { pathname, search } = req.nextUrl;

  if (isPublic(pathname)) {
    // Deliberately NOT auto-redirecting a signed-in visitor away from
    // /login or /register. That silent bounce was here originally and it
    // was wrong: from the visitor's side, clicking "Create your terminal"
    // just vanished straight to the dashboard with no form and no
    // explanation — indistinguishable from a bug. An existing session
    // (e.g. testing registration earlier, or a colleague sharing the
    // machine) is exactly when someone most needs to SEE that they're
    // already signed in, not have it decided for them. Both pages now
    // show that state themselves and offer a real choice.
    return NextResponse.next();
  }

  if (req.cookies.get(SESSION_COOKIE)) return NextResponse.next();

  // An API call answers 401 as JSON. Redirecting a fetch to an HTML login page
  // makes the client parse markup as data and report a confusing error.
  if (pathname.startsWith("/api/")) {
    return NextResponse.json(
      { ok: false, error: "unauthenticated" },
      { status: 401 },
    );
  }

  // Carry where they were headed so login can return them there. Only the
  // path+query, never an absolute URL — an attacker-supplied absolute `next`
  // is an open-redirect.
  const to = new URL("/login", req.url);
  to.searchParams.set("next", pathname + search);
  return NextResponse.redirect(to);
}

export const config = {
  /**
   * Everything except Next's own assets and the favicon. Static files carry no
   * user data and excluding them keeps the middleware off the hot path.
   */
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)"],
};
