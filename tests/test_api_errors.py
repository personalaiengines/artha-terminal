"""
ARTHA Terminal - global API error handling

The 29 per-route `try/except: return fail(e)` blocks were replaced by a single
Starlette exception handler.

It used to answer 200 + {"ok": false, "error": str(exc)}, which leaked SQLite
messages and absolute file paths to the browser and hid every failure from
monitoring behind a success code. Now: 500 + a fixed string, detail in the log
only. The front end still falls back correctly — fromApi (web/lib/api-server.ts:11)
returns null on any non-2xx.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from api.server import unhandled


async def _boom(req):
    raise RuntimeError("service down")


def test_unhandled_exception_returns_500_and_leaks_nothing():
    app = Starlette(routes=[Route("/api/boom", _boom)],
                    exception_handlers={Exception: unhandled})
    # raise_server_exceptions=False: Starlette re-raises after sending the
    # response so the server logs it — that must not fail the assertion here.
    r = TestClient(app, raise_server_exceptions=False).get("/api/boom")

    assert r.status_code == 500
    assert r.json() == {"ok": False, "error": "internal error"}
    assert "service down" not in r.text
