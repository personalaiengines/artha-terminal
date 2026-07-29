"""
ARTHA Terminal - Upstox authorization: cache invalidation

A successful token exchange has to invalidate every cached view of Upstox auth,
not just `upstox_status`. It didn't, so the banner re-read the still-warm
`system_status` entry and kept announcing "authorization has expired" after a
token that had actually worked — the API logs showed three successful exchanges
in 62 seconds because the user kept retrying a flow that had already succeeded.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

import api.server as server

DERIVED = ("upstox_status", "system_status", "data_health", "holdings", "portfolio_curve")


def _client(monkeypatch, result):
    import services.upstox_auth as auth
    monkeypatch.setattr(auth, "exchange_code", lambda code: result)
    for key in DERIVED:
        server._cache[key] = (9e9, {"stale": True})   # far-future ts = still warm
    app = Starlette(routes=[Route("/api/upstox/token", server.upstox_token, methods=["POST"])])
    return TestClient(app)


def test_successful_exchange_drops_every_derived_cache(monkeypatch):
    c = _client(monkeypatch, {"ok": True, "message": "saved"})
    r = c.post("/api/upstox/token", json={"code": "abc"})

    assert r.json()["ok"] is True
    still_cached = [k for k in DERIVED if k in server._cache]
    assert not still_cached, f"stale after authorize: {still_cached}"


def test_failed_exchange_keeps_caches(monkeypatch):
    # A rejected code changed nothing; throwing away good cached data would
    # just make every page pay a cold fetch for no reason.
    c = _client(monkeypatch, {"ok": False, "message": "Upstox rejected the code"})
    r = c.post("/api/upstox/token", json={"code": "bad"})

    assert r.json()["ok"] is False
    assert all(k in server._cache for k in DERIVED)
    for key in DERIVED:
        server._cache.pop(key, None)
