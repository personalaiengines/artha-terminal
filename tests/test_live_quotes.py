"""Upstox live-quote session dating (no network).

Stamping the candle with the wrong date silently corrupts price history, and
Upstox's OHLC response carries no date of its own — so the derivation is the
part worth pinning down.
"""

import asyncio
from datetime import datetime, timedelta

import services.live_quotes as lq


def _at(iso: str, holidays: set[str] | None = None) -> str:
    """session_date() as if `iso` (IST) were now."""
    real_dt, real_hol = lq.datetime, lq._holidays
    fixed = datetime.fromisoformat(iso).replace(tzinfo=lq.IST)

    class _DT(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed

    lq.datetime = _DT
    lq._holidays = holidays if holidays is not None else set()
    try:
        return asyncio.run(lq.session_date())
    finally:
        lq.datetime, lq._holidays = real_dt, real_hol


def test_during_session_is_today():
    assert _at("2026-07-28T11:00:00") == "2026-07-28"   # Tuesday, mid-session


def test_after_close_is_still_today():
    assert _at("2026-07-28T23:50:00") == "2026-07-28"


def test_before_open_rolls_back():
    """00:30 IST Wednesday still describes Tuesday's session, not Wednesday's."""
    assert _at("2026-07-29T00:30:00") == "2026-07-28"
    assert _at("2026-07-29T09:00:00") == "2026-07-28"


def test_weekend_rolls_back_to_friday():
    assert _at("2026-07-26T12:00:00") == "2026-07-24"   # Sunday -> Friday
    assert _at("2026-07-25T12:00:00") == "2026-07-24"   # Saturday -> Friday


def test_holiday_is_skipped():
    # If Friday the 24th were a holiday, Sunday must fall through to Thursday.
    assert _at("2026-07-26T12:00:00", holidays={"2026-07-24"}) == "2026-07-23"


def test_key_is_isin_based():
    """Ticker-form keys return an empty data map from Upstox."""
    from services.upstox import _equity_key, _isin_for
    if not _isin_for("RELIANCE"):
        return  # no seeded universe in this checkout
    assert _equity_key("RELIANCE") == "NSE_EQ|INE002A01018"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok {name}")
