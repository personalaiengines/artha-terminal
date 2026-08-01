"""
ARTHA Terminal - Upstox WebSocket market-data streaming

Activates upstox-python-sdk's MarketDataStreamerV3 (listed in requirements.txt
but unused until now) on top of the existing daily-refreshed OAuth
access_token — no changes to auth/token-refresh, same token
services/upstox.py already uses for portfolio calls.

Ticks land in an in-memory cache only (no per-tick DB write — prices_daily is
a daily-candle table, not built for tick rate) and fan out to subscriber
callbacks (api/ws.py registers one to push to connected browser clients).

The SDK's own connect() already spawns a background thread and does its own
short-run reconnect (5 attempts, 1s apart) before giving up and emitting
"autoReconnectStopped". This manager only needs to handle what happens after
that: keep retrying indefinitely with a capped exponential backoff, since a
live trading session runs for hours, not seconds.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

from config import config

logger = logging.getLogger("services.upstox_stream")

_MAX_BACKOFF_SECONDS = 60


class UpstoxStreamManager:
    """One instance per process. `start()` is idempotent; `subscribe()` can be
    called before or after `start()`."""

    def __init__(self):
        self._streamer = None
        self._active_keys: set[str] = set()
        self._tick_cache: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._subscribers: list[Callable[[str, dict], None]] = []
        self._started = False
        self._backoff_seconds = 2
        # Liveness, for services/data_health.py: the UI has to be able to say
        # "index ticks are not live" rather than quietly showing the last
        # cached level as if it were current.
        self._connected = False
        self._last_tick_at: float | None = None

    # -- public API ---------------------------------------------------
    def on_tick(self, callback: Callable[[str, dict], None]) -> None:
        """Register callback(instrument_key, tick) fired on every tick."""
        self._subscribers.append(callback)

    def get_cached_tick(self, instrument_key: str) -> Optional[dict]:
        return self._tick_cache.get(instrument_key)

    def subscribe(self, instrument_keys: list[str], mode: str = "ltpc") -> None:
        """Dedupe against currently-subscribed keys, then subscribe on the live
        feeder if connected. If not connected yet, the keys are picked up as
        part of the initial subscription list on the next connect."""
        new_keys = [k for k in instrument_keys if k not in self._active_keys]
        if not new_keys:
            return
        self._active_keys.update(new_keys)
        if self._streamer is not None:
            try:
                self._streamer.subscribe(new_keys, mode)
            except Exception as e:
                # Feeder may not be open yet (race right after connect()) —
                # the keys are already in _active_keys so a reconnect picks
                # them up; this is a rare, self-healing edge case.
                logger.warning(f"Upstox stream subscribe failed for {new_keys}: {e}")

    def start(self, initial_keys: Optional[list[str]] = None) -> None:
        """Idempotent. Non-blocking — the SDK spawns its own thread for the WS
        connection and returns immediately."""
        if self._started:
            return
        self._started = True
        if initial_keys:
            self._active_keys.update(initial_keys)
        self._connect()

    # -- internals ------------------------------------------------------
    def _connect(self) -> None:
        # Market data, so the market-data credential comes first. This used to
        # use the PORTFOLIO token only, and that token expires daily — the feed
        # handshake then 401'd and no tick ever reached the app, while the
        # perfectly valid analytics token sat unused and served REST quotes.
        access_token = config.upstox.analytics_token or config.upstox.access_token
        if not access_token:
            logger.error("No Upstox token configured — cannot start market-data stream")
            return

        import upstox_client

        configuration = upstox_client.Configuration()
        configuration.access_token = access_token
        api_client = upstox_client.ApiClient(configuration)
        streamer = upstox_client.MarketDataStreamerV3(
            api_client, instrumentKeys=list(self._active_keys), mode="ltpc",
        )
        streamer.on("open", self._on_open)
        streamer.on("message", self._on_message)
        streamer.on("error", self._on_error)
        streamer.on("close", self._on_close)
        streamer.on("autoReconnectStopped", self._on_reconnect_exhausted)
        self._streamer = streamer
        try:
            streamer.connect()
        except Exception as e:
            logger.error(f"Upstox stream connect() raised: {e}")
            self._on_reconnect_exhausted(str(e))

    def status(self) -> dict:
        """{started, connected, last_tick_age_s} — no I/O, safe to poll."""
        age = None if self._last_tick_at is None else time.time() - self._last_tick_at
        return {"started": self._started, "connected": self._connected,
                "last_tick_age_s": age, "subscribed": len(self._active_keys)}

    def _on_open(self, *_args) -> None:
        logger.info("Upstox market-data stream connected")
        self._connected = True
        self._backoff_seconds = 2

    def _on_message(self, data: dict) -> None:
        feeds = (data or {}).get("feeds") or {}
        now = time.time()
        for key, feed in feeds.items():
            tick = _parse_feed(feed, now)
            self._last_tick_at = now
            with self._lock:
                self._tick_cache[key] = tick
            for cb in self._subscribers:
                try:
                    cb(key, tick)
                except Exception as e:
                    logger.warning(f"Upstox tick subscriber failed: {e}")

    def _on_error(self, message) -> None:
        logger.warning(f"Upstox stream error: {message}")

    def _on_close(self, *args) -> None:
        self._connected = False
        logger.warning(f"Upstox stream closed: {args}")

    def _on_reconnect_exhausted(self, *_args) -> None:
        self._connected = False
        # ponytail: capped exponential backoff via threading.Timer, no jitter
        # — add jitter if reconnect storms become an issue with >1 process.
        delay = self._backoff_seconds
        self._backoff_seconds = min(self._backoff_seconds * 2, _MAX_BACKOFF_SECONDS)
        logger.warning(f"Upstox stream reconnect exhausted; retrying in {delay}s")
        threading.Timer(delay, self._connect).start()


def _parse_feed(feed: dict, received_at: float) -> dict:
    """Normalise one instrument's v3 feed payload into a compact tick. Pure
    function so it's unit-testable without a live connection."""
    ltpc = (
        feed.get("ltpc")
        or feed.get("fullFeed", {}).get("marketFF", {}).get("ltpc")
        or feed.get("firstLevelWithGreeks", {}).get("ltpc")
        or {}
    )
    return {
        "ltp": ltpc.get("ltp"),
        "ltt": ltpc.get("ltt"),
        "ltq": ltpc.get("ltq"),
        "close": ltpc.get("cp"),
        "received_at": received_at,
        "raw": feed,
    }


_manager: Optional[UpstoxStreamManager] = None


def get_stream_manager() -> UpstoxStreamManager:
    global _manager
    if _manager is None:
        _manager = UpstoxStreamManager()
    return _manager


if __name__ == "__main__":
    # Manual smoke test — connects live for ~10s and prints ticks. Run with a
    # real UPSTOX_ACCESS_TOKEN in .env; not part of the automated test suite.
    logging.basicConfig(level=logging.INFO)
    from services.upstox import INDEX_KEYS

    mgr = get_stream_manager()
    mgr.on_tick(lambda key, tick: print(key, tick))
    mgr.start(initial_keys=[INDEX_KEYS["nifty50"]])
    time.sleep(10)
