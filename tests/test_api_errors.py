"""
ARTHA Terminal - global API error handling

The 29 per-route `try/except: return fail(e)` blocks were replaced by a single
Starlette exception handler. The front end depends on a failing endpoint
answering 200 + {"ok": false} (that is its cue to fall back), so pin that down.
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


def test_unhandled_exception_returns_ok_false_with_200():
    app = Starlette(routes=[Route("/api/boom", _boom)],
                    exception_handlers={Exception: unhandled})
    # raise_server_exceptions=False: Starlette re-raises after sending the
    # response so the server logs it — that must not fail the assertion here.
    r = TestClient(app, raise_server_exceptions=False).get("/api/boom")

    assert r.status_code == 200
    assert r.json() == {"ok": False, "error": "service down"}
