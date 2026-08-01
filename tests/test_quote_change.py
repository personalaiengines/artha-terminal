"""
ARTHA Terminal - Upstox quote day-change derivation

The bug this pins: after the session settles, `ohlc.close` becomes TODAY's
close (== last_price), and the old code fell back to `(last - open) / open`.
On 2026-07-28 that printed Nifty 50 as +14.11 points (23985.35 against its
23971.25 open) when the index actually finished 10.60 points DOWN.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.upstox import _quote_change


def test_settled_session_uses_net_change_not_the_open():
    # Verbatim from Upstox /market-quote/quotes for NSE_INDEX|Nifty 50.
    last, prev, pct = _quote_change({
        "ohlc": {"open": 23971.25, "high": 24041.15, "low": 23954.6, "close": 23985.35},
        "last_price": 23985.35,
        "net_change": -10.6,
    })
    assert last == 23985.35
    assert round(prev, 2) == 23995.95
    assert pct < 0                                   # down day, not up
    assert round(last * pct / 100, 2) == -10.60      # the broker's own number


def test_live_session_falls_back_to_previous_close():
    # Mid-session: ohlc.close is genuinely yesterday's close and net_change
    # is absent from the payload.
    last, prev, pct = _quote_change({
        "ohlc": {"open": 100.0, "close": 100.0},
        "last_price": 110.0,
    })
    assert (last, prev) == (110.0, 100.0)
    assert round(pct, 2) == 10.0


def test_no_trustworthy_baseline_reports_no_change():
    # last == ohlc.close and no net_change: nothing to measure against. Must
    # be None, not a number derived from the opening print.
    _last, _prev, pct = _quote_change({"ohlc": {"open": 90.0, "close": 100.0},
                                       "last_price": 100.0})
    assert pct is None


def test_flat_day_is_zero_not_missing():
    _last, prev, pct = _quote_change({"ohlc": {"open": 99.0, "close": 100.0},
                                      "last_price": 100.0, "net_change": 0.0})
    assert prev == 100.0 and pct == 0.0
