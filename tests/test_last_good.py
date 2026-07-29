"""
ARTHA Terminal - last known-good fallback

When an upstream can't be reached the app must serve the previous good values,
flagged with when they were good — never a blank panel, and never a
differently-shaped substitute computed from another source.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from db import get_connection
from services import last_good


def _clear(key="t:pulse"):
    with get_connection() as conn:
        conn.execute("DELETE FROM last_good WHERE key = ?", (key,))
        conn.commit()


def test_success_persists_and_is_not_marked_stale():
    _clear()
    out = last_good.serve("t:pulse", lambda: {"sectors": [1], "ok": True})

    assert out["stale"] is False and out["as_of"] is None
    payload, saved_at = last_good.load("t:pulse")
    assert payload["sectors"] == [1] and saved_at
    _clear()


def test_failure_serves_the_previous_payload_with_its_timestamp():
    _clear()
    last_good.serve("t:pulse", lambda: {"sectors": ["good"], "ok": True})

    def boom():
        raise RuntimeError("yfinance rate limited")

    out = last_good.serve("t:pulse", boom)
    assert out["sectors"] == ["good"]
    assert out["stale"] is True and out["as_of"]
    assert out["ok"] is True          # real data — the page still renders
    _clear()


def test_empty_result_counts_as_failure_not_success():
    # /api/pulse can answer with no sectors at all; storing that would overwrite
    # good data with an empty payload and permanently blank the heatmap.
    _clear()
    last_good.serve("t:pulse", lambda: {"sectors": ["good"]},
                    is_good=lambda v: bool(v.get("sectors")))
    out = last_good.serve("t:pulse", lambda: {"sectors": []},
                          is_good=lambda v: bool(v.get("sectors")))

    assert out["sectors"] == ["good"] and out["stale"] is True
    payload, _ = last_good.load("t:pulse")
    assert payload["sectors"] == ["good"], "an empty result must not overwrite good data"
    _clear()


def test_nothing_ever_stored_reports_not_ok():
    _clear()

    def boom():
        raise RuntimeError("cold start, upstream down")

    out = last_good.serve("t:pulse", boom)
    assert out["ok"] is False and out["stale"] is True and out["as_of"] is None
