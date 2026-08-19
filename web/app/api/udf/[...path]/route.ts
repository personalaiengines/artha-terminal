import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { SESSION_COOKIE } from "@/middleware";

// Raw passthrough to the API's UDF datafeed, so the TradingView widget can talk to
// ARTHA same-origin. Deliberately NOT fromApi()/sendApi(): UDF answers /time with a
// bare Unix integer (JSON.parse survives that, but nothing else here is JSON) and
// reports failure as {"s":"error"}, which fromApi()'s ok:false rule would turn into
// null. The widget needs the bytes verbatim, so the body is forwarded as text with
// the upstream content-type.
//
// Same BASE and the same discipline as lib/api-server.ts: nothing from the BROWSER
// is forwarded — no cookies, no client headers — and no token reaches the browser.
// The API is default-deny (bearer middleware), so this hop reads the httpOnly
// session cookie itself and attaches it as the one header the browser never sees.
const BASE = process.env.ARTHA_API_URL ?? "http://localhost:8000";

async function authHeader(): Promise<Record<string, string>> {
  try {
    const token = (await cookies()).get(SESSION_COOKIE)?.value;
    return token ? { Authorization: `Bearer ${token}` } : {};
  } catch {
    return {};
  }
}

async function proxy(req: Request, path: string[], method: "GET" | "POST" | "DELETE") {
  const url = `${BASE}/api/udf/${path.map(encodeURIComponent).join("/")}${new URL(req.url).search}`;
  const ctrl = new AbortController();
  // Generous on purpose: /history on an intraday resolution lazy-fills the bar store
  // from Upstox on a cold cache — measured at 33s for NIFTY 5m, 18ms once warm.
  // Cutting that short would surface as a phantom "no data" in the widget.
  const t = setTimeout(() => ctrl.abort(), 60000);
  try {
    // /history over a long range is the slow one; GET has no body to relay.
    const body = method === "GET" ? undefined : await req.text();
    const res = await fetch(url, {
      method, signal: ctrl.signal, cache: "no-store",
      // Content-Type is a description of our own body, not a client credential —
      // chart-layout saves (step 7) are form-encoded, not JSON.
      headers: {
        ...(body ? { "Content-Type": req.headers.get("content-type") ?? "application/json" } : {}),
        ...(await authHeader()),
      },
      body: body || undefined,
    });
    return new NextResponse(await res.text(), {
      status: res.status,
      headers: {
        "content-type": res.headers.get("content-type") ?? "text/plain",
        "cache-control": "no-store",
      },
    });
  } catch {
    // Answer in the widget's own vocabulary — an HTML error page would surface as an
    // unparseable-datafeed crash instead of "no data".
    return NextResponse.json({ s: "error", errmsg: "datafeed unreachable" }, { status: 502 });
  } finally {
    clearTimeout(t);
  }
}

type Ctx = { params: Promise<{ path: string[] }> };

export async function GET(req: Request, { params }: Ctx) {
  return proxy(req, (await params).path, "GET");
}

export async function POST(req: Request, { params }: Ctx) {
  return proxy(req, (await params).path, "POST");
}

export async function DELETE(req: Request, { params }: Ctx) {
  return proxy(req, (await params).path, "DELETE");
}
