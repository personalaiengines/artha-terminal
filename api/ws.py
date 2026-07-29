"""
ARTHA Terminal - Stateful WebSocket endpoint

Pushes live Upstox ticks (and, generically, any other topic — alerts, news)
to connected browser clients instead of them polling REST.

Runs entirely on the asyncio event loop as a normal Starlette WebSocketRoute
— it never touches _POOL/_LLM_POOL (api/server.py), which only ever run
brief run_in_executor calls per REST request. The one thing to get right:
services.upstox_stream's tick callback fires on the Upstox SDK's own
background thread, not the event loop, so broadcast_tick crosses that
boundary via loop.call_soon_threadsafe rather than touching asyncio objects
directly from the wrong thread.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from starlette.websockets import WebSocket, WebSocketDisconnect

logger = logging.getLogger("api.ws")


def _resolve_key(sym_or_key: str) -> str:
    """Frontend clients subscribe with plain symbols they already have
    (stock.symbol, e.g. "RELIANCE") or friendly index names (e.g.
    "nifty50") rather than Upstox's pipe-delimited instrument keys — resolve
    here so the TS client never needs to know that format."""
    if "|" in sym_or_key:
        return sym_or_key
    from services.upstox import INDEX_KEYS, _equity_key
    key = INDEX_KEYS.get(sym_or_key.lower())
    return key or _equity_key(sym_or_key)


class ConnectionManager:
    def __init__(self):
        self.clients: dict[WebSocket, set[str]] = {}
        self._queues: dict[WebSocket, asyncio.Queue] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        # Upstox instrument key -> the name the client subscribed with.
        #
        # Equities resolve to their ISIN key (`NSE_EQ|INE002A01018`), so a tick
        # broadcast under that key never matched a browser handler registered
        # under "RELIANCE" — every equity tick was silently dropped and stock
        # prices only ever moved on the REST poll. Ticks now carry the caller's
        # own name alongside the key.
        self._names: dict[str, str] = {}

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.clients[ws] = set()
        self._queues[ws] = asyncio.Queue()
        if self._loop is None:
            self._loop = asyncio.get_running_loop()

    def disconnect(self, ws: WebSocket) -> None:
        self.clients.pop(ws, None)
        self._queues.pop(ws, None)

    def subscribe(self, ws: WebSocket, keys: list[str]) -> None:
        if ws not in self.clients or not keys:
            return
        resolved = []
        for name in keys:
            key = _resolve_key(name)
            resolved.append(key)
            self._names[key] = name
        self.clients[ws].update(resolved)
        from services.upstox_stream import get_stream_manager
        get_stream_manager().subscribe(resolved)

    def broadcast_tick(self, instrument_key: str, tick: dict) -> None:
        """Called from the Upstox SDK's own callback thread — cross into the
        event loop via call_soon_threadsafe, never touch the queues directly."""
        if self._loop is None:
            return
        payload = {"type": "tick", "key": instrument_key,
                   "symbol": self._names.get(instrument_key, instrument_key),
                   "tick": tick}
        for ws, keys in list(self.clients.items()):
            if instrument_key in keys:
                q = self._queues.get(ws)
                if q is not None:
                    self._loop.call_soon_threadsafe(q.put_nowait, payload)

    def broadcast_topic(self, topic: str, payload: dict) -> None:
        """For same-loop callers (e.g. an async scheduler job) — no thread
        crossing needed, so a plain put_nowait is enough."""
        msg = {"type": topic, "payload": payload}
        for ws in list(self.clients.keys()):
            q = self._queues.get(ws)
            if q is not None:
                q.put_nowait(msg)

    async def _drain(self, ws: WebSocket) -> None:
        q = self._queues[ws]
        while True:
            msg = await q.get()
            await ws.send_json(msg)


manager = ConnectionManager()


async def ws_endpoint(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    drain_task = asyncio.create_task(manager._drain(websocket))
    try:
        while True:
            msg = await websocket.receive_json()
            if msg.get("action") == "subscribe":
                manager.subscribe(websocket, msg.get("keys") or [])
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"ws_endpoint error: {e}")
    finally:
        drain_task.cancel()
        manager.disconnect(websocket)
