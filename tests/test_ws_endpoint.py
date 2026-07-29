"""
ARTHA Terminal - WS endpoint tests

A client connects, subscribes to an instrument key, and a broadcast_tick()
call for that key should reach it — while a tick for a key it never
subscribed to should not. Uses Starlette's built-in TestClient.websocket_connect
(no new test dependency).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from starlette.applications import Starlette
from starlette.routing import WebSocketRoute
from starlette.testclient import TestClient

from api.ws import ws_endpoint, manager


def _fresh_app():
    # Reset shared state between tests — `manager` is a module-level singleton.
    manager.clients.clear()
    manager._queues.clear()
    manager._loop = None
    return Starlette(routes=[WebSocketRoute("/ws", ws_endpoint)])


def test_subscribe_then_broadcast_tick_reaches_client():
    app = _fresh_app()
    with TestClient(app).websocket_connect("/ws") as ws:
        ws.send_json({"action": "subscribe", "keys": ["NSE_INDEX|Nifty 50"]})

        # Give the subscribe message a moment to be processed by the endpoint
        # before broadcasting — TestClient runs the app in a background thread.
        import time
        time.sleep(0.1)

        manager.broadcast_tick("NSE_INDEX|Nifty 50", {"ltp": 24000.0})
        msg = ws.receive_json()

    assert msg == {"type": "tick", "key": "NSE_INDEX|Nifty 50",
                   "symbol": "NSE_INDEX|Nifty 50", "tick": {"ltp": 24000.0}}


def test_equity_tick_carries_the_name_the_client_subscribed_with():
    """Upstox keys equities by ISIN, so a tick broadcast under
    `NSE_EQ|INE002A01018` never matched a browser handler registered under
    "RELIANCE" — every equity tick was dropped and stock prices only moved on
    the REST poll. The tick must echo the caller's own name."""
    app = _fresh_app()
    with TestClient(app).websocket_connect("/ws") as ws:
        ws.send_json({"action": "subscribe", "keys": ["RELIANCE"]})

        import time
        time.sleep(0.1)

        # Whatever key RELIANCE resolved to server-side is what the feed uses.
        key = next(iter(next(iter(manager.clients.values()))))
        assert key != "RELIANCE", "expected an Upstox instrument key, not the ticker"

        manager.broadcast_tick(key, {"ltp": 1450.5, "close": 1440.0})
        msg = ws.receive_json()

    assert msg["symbol"] == "RELIANCE"
    assert msg["tick"]["ltp"] == 1450.5


def test_tick_for_unsubscribed_key_does_not_reach_client():
    app = _fresh_app()
    with TestClient(app).websocket_connect("/ws") as ws:
        ws.send_json({"action": "subscribe", "keys": ["NSE_INDEX|Nifty 50"]})

        import time
        time.sleep(0.1)

        # Broadcast a different key, then a subscribed one — the client
        # should only ever see the subscribed key's tick, proving the
        # unsubscribed one wasn't queued ahead of it.
        manager.broadcast_tick("NSE_INDEX|Nifty Bank", {"ltp": 50000.0})
        manager.broadcast_tick("NSE_INDEX|Nifty 50", {"ltp": 24000.0})
        msg = ws.receive_json()

    assert msg["key"] == "NSE_INDEX|Nifty 50"
