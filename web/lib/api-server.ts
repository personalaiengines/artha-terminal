// Server-only helper: fetch from the Python (Starlette) API with a hard timeout.
// Returns null on any failure so route handlers fall back to mock. The base URL
// is the in-cluster service in Docker (http://api:8000) or localhost in dev.
import { cookies } from "next/headers";
import { SESSION_COOKIE } from "@/middleware";

const BASE = process.env.ARTHA_API_URL ?? "http://localhost:8000";

/**
 * The caller's session token, read from the httpOnly cookie.
 *
 * Every proxied call carries it, because the Python API is default-deny — a
 * request without it is rejected. This is also the reason the browser is never
 * given the token: it reaches the API only through this server-side hop, so
 * there is no path by which a script on the page can call the API directly.
 *
 * Returns undefined outside a request scope (a build-time render, say), where
 * `cookies()` throws. The call then goes out unauthenticated and the API
 * answers 401, which is the correct outcome — better than crashing the render.
 */
async function authHeader(): Promise<Record<string, string>> {
  try {
    const token = (await cookies()).get(SESSION_COOKIE)?.value;
    return token ? { Authorization: `Bearer ${token}` } : {};
  } catch {
    return {};
  }
}

// `keepError` returns the ok:false body instead of null. Broker routes need it:
// /api/positions and /api/holdings answer an expired session with ok:false plus
// the *reason* (status/message), and collapsing that to null made the F&O book
// render "The broker session is error" instead of "Access token expired". Stays
// opt-in — every other route relies on null meaning "fall back to mock".
export async function fromApi<T = any>(
  path: string, timeoutMs = 4000, keepError = false
): Promise<T | null> {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${BASE}${path}`, {
      signal: ctrl.signal,
      cache: "no-store",
      headers: await authHeader(),
    });
    if (!res.ok) return null;
    const json = await res.json();
    if (json && json.ok === false && !keepError) return null;
    return json as T;
  } catch {
    return null;
  } finally {
    clearTimeout(t);
  }
}

// POST/DELETE proxies for write endpoints (AI query, alerts CRUD). Return the
// parsed body (even ok:false) so the caller can surface failures, or null on
// network/timeout error.
export async function sendApi<T = any>(
  path: string, method: "POST" | "DELETE", body?: unknown, timeoutMs = 20000
): Promise<T | null> {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${BASE}${path}`, {
      method, signal: ctrl.signal, cache: "no-store",
      headers: {
        ...(body ? { "Content-Type": "application/json" } : {}),
        ...(await authHeader()),
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    return (await res.json()) as T;
  } catch {
    return null;
  } finally {
    clearTimeout(t);
  }
}
