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
    manager._names.clear()
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
                   "symbol": "NSE_INDEX|Nifty 50",
                   "symbols": ["NSE_INDEX|Nifty 50"], "tick": {"ltp": 24000.0}}


def test_two_aliases_for_one_instrument_both_get_the_tick():
    """The topbar ticker subscribes "nifty50"; a hook that upper-cases its input
    subscribes "NIFTY50". Both resolve to `NSE_INDEX|Nifty 50`, and the tick used
    to echo only the name that arrived last — so whichever component mounted
    first silently stopped receiving ticks while its socket and its subscription
    both stayed perfectly healthy. That is how the F&O page's spot price sat
    frozen on a cached chain value with a live index ticker directly above it.
    """
    app = _fresh_app()
    with TestClient(app).websocket_connect("/ws") as ws:
        ws.send_json({"action": "subscribe", "keys": ["nifty50"]})
        ws.send_json({"action": "subscribe", "keys": ["NIFTY50"]})

        import time
        time.sleep(0.1)

        manager.broadcast_tick("NSE_INDEX|Nifty 50", {"ltp": 24000.0})
        msg = ws.receive_json()

    assert sorted(msg["symbols"]) == ["NIFTY50", "nifty50"]
    # Still one string for anything reading the old field.
    assert msg["symbol"] in msg["symbols"]


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


def test_subscribe_cap_bounds_the_connection_not_the_frame():
    """The cap used to slice the incoming list, which bounded nothing: the real
    client subscribes one symbol per frame (web/lib/use-live-prices.ts), so
    N frames still grew the connection's set without limit.
    """
    from api.ws import _MAX_KEYS

    app = _fresh_app()
    with TestClient(app).websocket_connect("/ws") as ws:
        # One key per frame, well past the cap — the shape the real client uses.
        for i in range(_MAX_KEYS + 50):
            ws.send_json({"action": "subscribe", "keys": [f"NSE_EQ|SYM{i:05d}"]})

        import time
        time.sleep(0.2)

        held = next(iter(manager.clients.values()))

    assert len(held) <= _MAX_KEYS, f"connection grew to {len(held)}, cap is {_MAX_KEYS}"
