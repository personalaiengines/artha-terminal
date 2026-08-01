"""Intraday bar store + resampler (services/intraday.py).

The bug class this file exists to kill: 5m/15m/1h bars are COMPUTED, not
fetched (Upstox rejects those intervals outright), so a wrong aggregation or a
mis-parsed +05:30 timestamp would silently draw a plausible, wrong chart.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from services import intraday


def _bar(t, o, h, l, c, v):
    return {"t": t, "open": o, "high": h, "low": l, "close": c, "volume": v}


# 2026-07-31 09:15:00 IST = 03:45:00 UTC
OPEN = 1785469500
FUTURE = OPEN + 10 ** 7   # a `now` far past the series, so nothing is partial


def test_upstox_offset_is_honoured():
    """+05:30 parsed as local time would shift every bar by 19800s."""
    assert intraday._epoch("2026-07-31T09:15:00+05:30") == OPEN
    assert intraday._epoch("2026-07-31T03:45:00+00:00") == OPEN
    assert intraday._epoch("garbage") is None


def test_buckets_anchor_on_the_session_open():
    # 09:15 IST is not on a UTC hour boundary: a 60m bar must start at 09:15,
    # not 09:00.
    assert intraday._bucket(OPEN, 3600) == OPEN
    assert intraday._bucket(OPEN + 3599, 3600) == OPEN
    assert intraday._bucket(OPEN + 3600, 3600) == OPEN + 3600
    # 5m/15m happen to also land on epoch boundaries, which UDF clients assume.
    assert intraday._bucket(OPEN + 61, 300) % 300 == 0


def test_five_minute_ohlcv_is_first_max_min_last_sum():
    bars = [_bar(OPEN + i * 60, 100 + i, 110 + i, 90 + i, 105 + i, 10) for i in range(10)]
    out = intraday.resample(bars, 5, now=FUTURE)

    assert len(out) == 2
    assert out[0]["t"] == OPEN and out[1]["t"] == OPEN + 300
    assert out[0]["open"] == 100          # first
    assert out[0]["high"] == 114          # max (bar 4)
    assert out[0]["low"] == 90            # min (bar 0)
    assert out[0]["close"] == 109         # last (bar 4)
    assert out[0]["volume"] == 50         # sum
    assert out[0]["n"] == 5
    assert out[1]["open"] == 105 and out[1]["close"] == 114 and out[1]["volume"] == 50


def test_fifteen_minute_folds_the_same_bars():
    bars = [_bar(OPEN + i * 60, 100 + i, 110 + i, 90 + i, 105 + i, 10) for i in range(10)]
    out = intraday.resample(bars, 15, now=FUTURE)

    assert len(out) == 1
    assert out[0] == {"t": OPEN, "open": 100, "high": 119, "low": 90, "close": 114,
                      "volume": 100, "n": 10, "partial": False}


def test_a_hole_produces_no_bar_inside_the_hole():
    # 5 bars, a 20-minute hole, then 5 more. Nothing may be invented in between.
    bars = [_bar(OPEN + i * 60, 100, 100, 100, 100, 1) for i in range(5)]
    bars += [_bar(OPEN + 1500 + i * 60, 200, 200, 200, 200, 1) for i in range(5)]
    out = intraday.resample(bars, 5, now=FUTURE)

    assert [b["t"] for b in out] == [OPEN, OPEN + 1500]
    assert all(b["n"] == 5 for b in out)


def test_trailing_bucket_is_flagged_partial():
    bars = [_bar(OPEN + i * 60, 100, 100, 100, 100, 1) for i in range(7)]
    # `now` sits inside the second 5m bucket: it has 2 of its 5 minutes.
    out = intraday.resample(bars, 5, now=OPEN + 420)

    assert out[0]["partial"] is False and out[0]["n"] == 5
    assert out[1]["partial"] is True and out[1]["n"] == 2


@pytest.fixture()
def db(tmp_path):
    """A real database built from db/schema.sql - which is also the check that
    prices_intraday is actually IN schema.sql, not created ad hoc."""
    from db import init_database
    return init_database(tmp_path / "t.db")


def _seed(db, symbol, bars):
    from db import get_connection
    with get_connection(db) as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO prices_intraday "
            "(symbol, ts, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
            [(symbol, b["t"], b["open"], b["high"], b["low"], b["close"], b["volume"])
             for b in bars])


def test_read_and_coverage_round_trip(db):
    bars = [_bar(OPEN + i * 60, 100 + i, 110 + i, 90 + i, 105 + i, 10) for i in range(10)]
    _seed(db, "NIFTY", bars)

    assert intraday.coverage("NIFTY", db_path=db) == {
        "bars": 10, "first": OPEN, "last": OPEN + 540}

    # frm/to inside stored coverage -> no lazy fill, no network.
    out = intraday.read("NIFTY", 5, OPEN, OPEN + 540, db_path=db)
    assert [b["t"] for b in out] == [OPEN, OPEN + 300]
    assert out[0]["high"] == 114 and out[0]["volume"] == 50

    assert intraday.read("NIFTY", 7, OPEN, OPEN + 540, db_path=db) == []   # bad res
    assert intraday.read("NOTANINDEX", 5, OPEN, OPEN + 540, db_path=db) == []


def test_neighbour_ts_points_at_real_data_only(db):
    _seed(db, "NIFTY", [_bar(OPEN + i * 60, 100, 100, 100, 100, 1) for i in range(10)])

    # Window entirely before the data -> the first bar after it.
    assert intraday.neighbour_ts("NIFTY", OPEN - 7200, OPEN - 3600, db_path=db) == OPEN
    # Window entirely after -> the last bar before it.
    assert intraday.neighbour_ts("NIFTY", OPEN + 3600, OPEN + 7200,
                                 db_path=db) == OPEN + 540
    assert intraday.neighbour_ts("BANKNIFTY", 0, 10, db_path=db) is None
