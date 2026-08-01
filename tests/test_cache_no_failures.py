"""
ARTHA Terminal — a failed result must never be cached.

Regression: `/api/fno/nifty50` served {"ok": false, "error": "no option
expiries available"} in 0.0s (a cache hit) while `/api/fno/nifty50/expiries`
was concurrently returning all 18 expiries against the same healthy Upstox
session. `/api/positions` did the same with a blank error message. Both
recovered on process restart — the tell that the failure had been frozen into
the TTL cache rather than being a live upstream problem.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from api import server


def _clear():
    server._cache.clear()


def test_failed_result_is_not_stored():
    _clear()
    server._cache_put("fno:nifty50", {"ok": False, "error": "no option expiries available"})
    assert "fno:nifty50" not in server._cache


def test_successful_result_is_stored():
    _clear()
    server._cache_put("fno:nifty50", {"ok": True, "spot": 24383.6})
    assert server._cache["fno:nifty50"][1]["spot"] == 24383.6


def test_a_failure_does_not_evict_a_good_earlier_value():
    """The stale-while-revalidate refresh path calls _cache_put directly. A
    refresh that fails must leave the last good value in place, not blank it."""
    _clear()
    server._cache_put("k", {"ok": True, "spot": 1.0})
    server._cache_put("k", {"ok": False, "error": "upstream down"})
    assert server._cache["k"][1] == {"ok": True, "spot": 1.0}


def test_non_dict_values_are_unaffected():
    """Plenty of cached payloads are lists (candles, news items) — the guard
    must only inspect dicts, never reject a legitimate list or scalar."""
    _clear()
    server._cache_put("candles", [{"t": "2026-07-31", "close": 24383.6}])
    server._cache_put("count", 42)
    assert len(server._cache["candles"][1]) == 1
    assert server._cache["count"][1] == 42


def test_ok_absent_is_still_cached():
    """`ok` is attached by the `ok()` response helper, not by every service.
    A payload that simply never carries the key is not a failure."""
    _clear()
    server._cache_put("plain", {"spot": 24383.6})
    assert server._cache["plain"][1]["spot"] == 24383.6


def test_eviction_still_bounds_the_cache():
    _clear()
    for i in range(server._CACHE_MAX + 10):
        server._cache_put(f"k{i}", {"ok": True, "n": i})
    assert len(server._cache) == server._CACHE_MAX
    assert "k0" not in server._cache, "oldest key should have been evicted first"
