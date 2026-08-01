"""
ARTHA Terminal - Upstox stream manager tests

Covers the pure-function/dedup/backoff pieces that don't need a live
connection. The real end-to-end WS behavior is verified manually via
`python -m services.upstox_stream` against a real access token.
"""

import sys
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.upstox_stream import UpstoxStreamManager, _parse_feed


def test_parse_feed_extracts_ltpc():
    feed = {"ltpc": {"ltp": 24123.45, "ltt": "1700000000000", "ltq": 50, "cp": 24000.0}}
    tick = _parse_feed(feed, received_at=123.0)
    assert tick["ltp"] == 24123.45
    assert tick["close"] == 24000.0
    assert tick["received_at"] == 123.0
    assert tick["raw"] is feed


def test_parse_feed_falls_back_to_full_feed_shape():
    feed = {"fullFeed": {"marketFF": {"ltpc": {"ltp": 100.0, "cp": 99.0}}}}
    tick = _parse_feed(feed, received_at=1.0)
    assert tick["ltp"] == 100.0


def test_parse_feed_missing_ltpc_returns_none_fields():
    tick = _parse_feed({}, received_at=1.0)
    assert tick["ltp"] is None


def test_subscribe_dedupes_against_active_keys():
    mgr = UpstoxStreamManager()
    mgr._active_keys.update(["NSE_INDEX|Nifty 50"])
    # Streamer not connected — subscribe() should just update the active set,
    # not raise, and should not re-add an already-active key.
    mgr.subscribe(["NSE_INDEX|Nifty 50", "NSE_INDEX|Nifty Bank"])
    assert mgr._active_keys == {"NSE_INDEX|Nifty 50", "NSE_INDEX|Nifty Bank"}


def test_on_message_updates_cache_and_notifies_subscribers():
    mgr = UpstoxStreamManager()
    received = []
    mgr.on_tick(lambda key, tick: received.append((key, tick)))

    mgr._on_message({"feeds": {"NSE_INDEX|Nifty 50": {"ltpc": {"ltp": 24000.0}}}})

    assert received[0][0] == "NSE_INDEX|Nifty 50"
    assert mgr.get_cached_tick("NSE_INDEX|Nifty 50")["ltp"] == 24000.0


def test_reconnect_backoff_doubles_and_caps():
    mgr = UpstoxStreamManager()

    # Don't let threading.Timer actually schedule a real delayed call — just
    # assert the backoff counter's own math, which is what this test covers.
    with patch("services.upstox_stream.threading.Timer") as fake_timer:
        assert mgr._backoff_seconds == 2
        mgr._on_reconnect_exhausted()
        assert mgr._backoff_seconds == 4
        fake_timer.assert_called_with(2, mgr._connect)

        mgr._on_reconnect_exhausted()
        assert mgr._backoff_seconds == 8
        fake_timer.assert_called_with(4, mgr._connect)
