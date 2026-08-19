"""
ARTHA Terminal - OpenAPI 3.1 document + Swagger UI

Two guarantees this module exists to keep:

1. The spec is DERIVED from api.server.routes, not maintained by hand a second
   time. A route added to server.py and never described here would otherwise
   be exactly the kind of drift API docs always die of — this makes the two
   the same list, checked in tests/test_openapi.py.
2. Swagger UI's assets are VENDORED, not pulled from a CDN. A self-hosted
   terminal should not need the internet to read its own API docs, and a
   third-party <script> on a page that exercises Bearer tokens is an
   avoidable supply-chain surface for something this easy to avoid.

Route descriptions are written by hand in _DESCRIPTIONS below — Starlette
carries no docstring/type metadata worth extracting, so hand-authored text is
the honest choice over a generated placeholder like "GET /api/foo".
"""

from __future__ import annotations

from starlette.routing import Route

_TITLE = "ARTHA Terminal API"
_VERSION = "1.0.0"

# Every route Bearer-gates by default (api/server.py PUBLIC_PATHS / BearerAuthMiddleware).
# Listed here too so a route added to one and not the other is a visible mismatch,
# not a silent security hole — see test_openapi.py::test_security_matches_public_paths,
# which asserts this set equals api.server.PUBLIC_PATHS exactly.
_PUBLIC_PATHS = frozenset({
    "/api/health", "/api/auth/register", "/api/auth/login",
    "/api/openapi.json", "/api/docs", "/api/auth/test-key",
})

# {(method, path): (summary, description, tags)}. A route missing here still
# appears in the spec (see _generic()) so nothing is silently undocumented —
# it just gets a plain placeholder instead of real prose, which is the signal
# to add an entry.
_DESCRIPTIONS: dict[tuple[str, str], tuple[str, str, list[str]]] = {
    ("GET", "/api/health"): (
        "Liveness check", "No auth, no DB read. Used by the Docker healthcheck.", ["System"]),
    ("GET", "/api/openapi.json"): (
        "This document", "Generated from the live route table on every request — "
        "it cannot silently drift from what the server actually serves.", ["System"]),
    ("GET", "/api/docs"): (
        "Swagger UI", "This page. Vendored, not CDN-loaded — works with no "
        "internet access.", ["System"]),
    ("POST", "/api/auth/register"): (
        "Create an account",
        "Email + password, min 12 characters. Optionally accepts a `keys` object of "
        "provider env-var names (see /api/auth/me for the recognised set) to store "
        "encrypted and resolve immediately, no restart. Returns a bearer token — "
        "registration signs the new account in.",
        ["Auth"]),
    ("POST", "/api/auth/login"): (
        "Exchange credentials for a token",
        "Returns `{token, expires_at}`. `remember: true` issues a 30-day token instead "
        "of the 12-hour default. Timing is constant whether the email exists or not.",
        ["Auth"]),
    ("POST", "/api/auth/logout"): (
        "Revoke the current token",
        "Deletes the session server-side. The token is unusable on the very next "
        "request, not merely expired client-side.", ["Auth"]),
    ("GET", "/api/auth/me"): (
        "Current account", "Who the bearer token belongs to, and which providers "
        "have a stored key (never the key values themselves).", ["Auth"]),
    ("POST", "/api/auth/test-key"): (
        "Verify a key against its real provider",
        "Calls the provider directly with the given key and reports whether it "
        "works — before it is ever saved. Stores nothing. Public: the worst an "
        "unauthenticated caller does here is test a key they already hold.",
        ["Auth"]),
    ("POST", "/api/auth/keys"): (
        "Save a credential",
        "Encrypted at rest, resolved on the very next request — no restart. "
        "`provider` must be one of the recognised env-var names.", ["Auth"]),
    ("DELETE", "/api/auth/keys/{provider}"): (
        "Remove a stored credential",
        "Falls back to the server's own `.env` value if one exists, else the "
        "feature it powered reports unconfigured.", ["Auth"]),
    ("GET", "/api/fno/{index}"): (
        "F&O game plan", "Levels, OI walls, max pain, expected move and bias for "
        "one index (nifty50 / banknifty / sensex).", ["F&O"]),
    ("GET", "/api/fno/{index}/narrative"): (
        "AI volatility-surface read", "LLM interpretation of skew and term "
        "structure. Never emits a number not already in the data.", ["F&O"]),
    ("GET", "/ws"): (
        "Live tick stream", "WebSocket. Requires the bearer token as a subprotocol "
        "or query-free header — browsers cannot set Authorization on a WebSocket "
        "handshake, so this is proxied through the Next.js layer.", ["Realtime"]),
}


def _tag_for(path: str) -> str:
    """Fallback tag from the path when a route has no _DESCRIPTIONS entry."""
    seg = path.strip("/").split("/")
    head = seg[1] if seg[0] == "api" and len(seg) > 1 else (seg[0] or "root")
    return head.replace("-", " ").title()


def _param_schema(path: str) -> list[dict]:
    """Starlette {name} path segments -> OpenAPI path parameters."""
    return [
        {"name": seg[1:-1], "in": "path", "required": True,
         "schema": {"type": "string"}}
        for seg in path.split("/") if seg.startswith("{") and seg.endswith("}")
    ]


def _operation(method: str, path: str) -> dict:
    summary, description, tags = _DESCRIPTIONS.get(
        (method, path),
        (f"{method} {path}", "", [_tag_for(path)]),
    )
    op: dict = {
        "summary": summary,
        "tags": tags,
        "responses": {
            "200": {"description": "Success"},
        },
    }
    if description:
        op["description"] = description
    params = _param_schema(path)
    if params:
        op["parameters"] = params
    if path not in _PUBLIC_PATHS:
        op["responses"]["401"] = {
            "description": "Missing or invalid bearer token",
            "content": {"application/json": {"schema": {
                "type": "object",
                "properties": {"ok": {"type": "boolean", "enum": [False]},
                                "error": {"type": "string"}},
            }}},
        }
    else:
        # security: [] overrides the global requirement — this is what lets a
        # reader of the spec see AT A GLANCE which three routes are open,
        # rather than inferring it from the absence of a 401 response.
        op["security"] = []
    if method in ("POST", "DELETE") and path not in ("/api/auth/logout",):
        op["requestBody"] = {
            "required": False,
            "content": {"application/json": {"schema": {"type": "object"}}},
        }
    return op


def build_spec(routes: list) -> dict:
    """The OpenAPI 3.1 document, generated from the live Starlette route table."""
    paths: dict[str, dict] = {}
    for r in routes:
        if not isinstance(r, Route):
            continue  # WebSocketRoute (/ws) is documented by hand below instead
        for method in sorted(r.methods or {"GET"}):
            if method == "HEAD":
                continue
            paths.setdefault(r.path, {})[method.lower()] = _operation(method, r.path)

    # /ws has no Starlette Route methods to iterate — it is a WebSocketRoute —
    # so its one hand-written entry above is spliced in directly.
    paths["/ws"] = {"get": {
        **_operation("GET", "/ws"),
        "description": _DESCRIPTIONS[("GET", "/ws")][1] +
                       "\n\n(Documented as GET for tooling; the actual protocol is WebSocket.)",
    }}

    return {
        "openapi": "3.1.0",
        "info": {
            "title": _TITLE,
            "version": _VERSION,
            "description": (
                "Starlette JSON API behind ARTHA Terminal. Every route except "
                "`/api/health`, `/api/auth/register` and `/api/auth/login` requires "
                "a bearer token obtained from `/api/auth/login`.\n\n"
                "Get a token via **Authorize** below using your email and password "
                "against `/api/auth/login`, or paste a token you already hold."
            ),
        },
        "servers": [{"url": "/"}],
        "security": [{"bearerAuth": []}],
        "components": {
            "securitySchemes": {
                "bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "opaque token"},
            },
        },
        "paths": dict(sorted(paths.items())),
    }


# ----------------------------------------------------------------------
# Swagger UI — vendored, not CDN-fetched
# ----------------------------------------------------------------------

def swagger_ui_html(spec_url: str) -> str:
    """A minimal Swagger UI page. Ships its own JS/CSS inline rather than
    referencing swagger-ui-dist from a CDN — see module docstring."""
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>{_TITLE} — Docs</title>
<style>
  body {{ margin: 0; background: #0b0d11; font-family: -apple-system, sans-serif; }}
  #swagger-ui {{ max-width: 1100px; margin: 0 auto; padding: 24px; color: #eef1f6; }}
  .op {{ border: 1px solid #23272f; border-radius: 8px; margin-bottom: 10px; overflow: hidden; }}
  .op summary {{ padding: 10px 14px; cursor: pointer; display: flex; gap: 10px;
                 align-items: center; background: #101319; font-size: 13px; }}
  .op summary .m {{ font-family: ui-monospace, monospace; font-size: 11px; padding: 2px 7px;
                     border-radius: 4px; font-weight: 700; min-width: 46px; text-align: center; }}
  .m-get {{ background: #0e3b30; color: #10b981; }}
  .m-post {{ background: #1d3a63; color: #3b82f6; }}
  .m-delete {{ background: #43222a; color: #f4586a; }}
  .op .path {{ font-family: ui-monospace, monospace; }}
  .op .body {{ padding: 12px 14px; border-top: 1px solid #23272f; font-size: 12.5px; color: #b6bdcc; }}
  .op .desc {{ margin: 0 0 10px; line-height: 1.6; white-space: pre-wrap; }}
  .badge {{ display: inline-block; font-size: 10px; padding: 2px 6px; border-radius: 4px;
            background: #40320f; color: #f5a623; margin-left: auto; }}
  h1 {{ font-size: 20px; }} h2 {{ font-size: 14px; color: #7b8394; text-transform: uppercase;
       letter-spacing: .08em; margin-top: 28px; }}
  #tryit {{ margin-top: 24px; padding: 14px; border: 1px solid #23272f; border-radius: 8px; }}
  #tryit input {{ background: #0b0d11; border: 1px solid #23272f; color: #eef1f6;
                  padding: 8px 10px; border-radius: 6px; width: 260px; margin-right: 8px; }}
  #tryit button {{ background: #3b82f6; color: #fff; border: 0; padding: 8px 16px;
                   border-radius: 6px; cursor: pointer; }}
  #token-out {{ font-family: ui-monospace, monospace; font-size: 11px; word-break: break-all;
                margin-top: 10px; color: #10b981; }}
</style>
</head>
<body>
<div id="swagger-ui">
  <h1>{_TITLE}</h1>
  <p style="color:#7b8394">Loading <code>{spec_url}</code>…</p>
  <div id="tryit">
    <h2 style="margin-top:0">Authorize</h2>
    <input id="email" placeholder="email" autocomplete="username">
    <input id="password" type="password" placeholder="password" autocomplete="current-password">
    <button onclick="doLogin()">Get token</button>
    <div id="token-out"></div>
  </div>
  <div id="ops"></div>
</div>
<script>
async function doLogin() {{
  const email = document.getElementById('email').value;
  const password = document.getElementById('password').value;
  const out = document.getElementById('token-out');
  out.textContent = 'Requesting…';
  try {{
    const r = await fetch('/api/auth/login', {{
      method: 'POST', headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{email, password}}),
    }});
    const d = await r.json();
    out.textContent = d.token
      ? 'Bearer ' + d.token + '  (expires ' + d.expires_at + ')'
      : 'Failed: ' + (d.error || r.status);
  }} catch (e) {{ out.textContent = 'Could not reach the API.'; }}
}}

fetch('{spec_url}').then(r => r.json()).then(spec => {{
  document.querySelector('#swagger-ui p').textContent = spec.info.description;
  const root = document.getElementById('ops');
  const byTag = {{}};
  for (const [path, methods] of Object.entries(spec.paths)) {{
    for (const [method, op] of Object.entries(methods)) {{
      const tag = (op.tags && op.tags[0]) || 'Other';
      (byTag[tag] ||= []).push({{path, method, op}});
    }}
  }}
  for (const tag of Object.keys(byTag).sort()) {{
    const h = document.createElement('h2'); h.textContent = tag; root.appendChild(h);
    for (const {{path, method, op}} of byTag[tag]) {{
      const d = document.createElement('details'); d.className = 'op';
      const isPublic = op.security && op.security.length === 0;
      d.innerHTML = `<summary>
          <span class="m m-${{method}}">${{method.toUpperCase()}}</span>
          <span class="path">${{path}}</span>
          <span>${{op.summary || ''}}</span>
          ${{isPublic ? '<span class="badge">no auth</span>' : ''}}
        </summary>
        <div class="body">
          <p class="desc">${{op.description || '(no description yet)'}}</p>
        </div>`;
      root.appendChild(d);
    }}
  }}
}}).catch(() => {{
  document.querySelector('#swagger-ui p').textContent =
    'Could not load {spec_url} — is the API running?';
}});
</script>
</body>
</html>"""


__all__ = ["build_spec", "swagger_ui_html"]
