"""
ARTHA Terminal - index candle catch-up on startup

APScheduler never replays a cron fire the process was down for, so two rebuilds
across the 20:45 IST window left NIFTY/BANKNIFTY/SENSEX two sessions behind the
equities — the F&O chart drew its levels above the whole candle series and both
looked wrong. These pin the self-heal: it fires when the indices are behind, and
it does NOT re-fetch when they are current.

No network: `run` is monkeypatched and the DB is a tmp_path file.
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import ingestion.index_history as ih
from db import get_connection


def _db(tmp_path, monkeypatch, rows):
    """A prices_daily holding `rows` of (symbol, date), wired into the module."""
    path = tmp_path / "t.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE prices_daily (symbol TEXT, date TEXT, close REAL)")
    conn.executemany("INSERT INTO prices_daily VALUES (?, ?, 100)", rows)
    conn.commit()
    conn.close()
    monkeypatch.setattr(ih, "get_connection", lambda: get_connection(path))


def _spy(monkeypatch):
    calls = []
    monkeypatch.setattr(ih, "run", lambda period="1y": calls.append(period)
                        or {"status": "success", "indices": 3, "rows": 60})
    return calls


def test_stale_indices_trigger_a_backfill(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch, [("NIFTY", "2026-07-28"), ("RELIANCE", "2026-07-30")])
    calls = _spy(monkeypatch)

    res = ih.catch_up(target="2026-07-30")
    assert calls == ["1mo"], "a behind index must re-run the ingest"
    assert res["was"] == "2026-07-28" and res["target"] == "2026-07-30"


def test_current_indices_are_left_alone(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch, [("NIFTY", "2026-07-30"), ("RELIANCE", "2026-07-30")])
    calls = _spy(monkeypatch)

    res = ih.catch_up(target="2026-07-30")
    assert calls == [], "no fetch when nothing is behind"
    assert res["up_to_date"] is True


def test_target_falls_back_to_the_rest_of_the_table_not_the_indices(tmp_path, monkeypatch):
    # ingestion.quotes.latest_trading_date() reads MAX(date) of these very index
    # symbols, so using it as the target would always report "up to date" and the
    # gap would never heal. The equity tail is the honest comparison.
    import services.live_quotes as lq
    monkeypatch.setattr(lq, "available", lambda: False)
    _db(tmp_path, monkeypatch, [("NIFTY", "2026-07-28"), ("RELIANCE", "2026-07-30")])
    calls = _spy(monkeypatch)

    res = ih.catch_up()
    assert calls == ["1mo"]
    assert res["target"] == "2026-07-30"


def test_empty_table_is_skipped_not_crashed(tmp_path, monkeypatch):
    import services.live_quotes as lq
    monkeypatch.setattr(lq, "available", lambda: False)
    _db(tmp_path, monkeypatch, [])
    calls = _spy(monkeypatch)

    assert ih.catch_up()["status"] == "skipped"
    assert calls == []


def test_india_vix_is_ingested_alongside_the_indices():
    # R13 needs VIX history to compute a percentile from; the DB held zero rows.
    assert ih.INDEX_TICKERS["INDIAVIX"] == "^INDIAVIX"
