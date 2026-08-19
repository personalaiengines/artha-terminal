"""F&O P&L tracker: snapshot upsert, per-contract grain, curve, window stats.

Every row belongs to a user (`ME` below). `OTHER` writes the same dates and the
same contracts on purpose — the tracker must not see a single one of them.
"""

import sqlite3
from contextlib import contextmanager

import pytest

import services.fno_pnl as P

ME, OTHER = 1, 2


@pytest.fixture
def db(tmp_path, monkeypatch):
    conn = sqlite3.connect(tmp_path / "t.db")
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE fno_pnl_daily (
        user_id INTEGER, date TEXT, realized REAL, unrealized REAL, net REAL,
        open_count INTEGER, closed_count INTEGER, updated_at TEXT,
        source TEXT DEFAULT 'live', PRIMARY KEY (user_id, date))""")
    conn.execute("""CREATE TABLE fno_pnl_contract_daily (
        user_id INTEGER, date TEXT, symbol TEXT, realized REAL, unrealized REAL,
        net REAL, qty INTEGER, updated_at TEXT,
        PRIMARY KEY (user_id, date, symbol))""")

    @contextmanager
    def _conn(*a, **k):
        yield conn

    monkeypatch.setattr(P, "get_connection", _conn)
    return conn


def _day(db, date, net, source="live", user=ME):
    db.execute("INSERT INTO fno_pnl_daily VALUES (?,?,0,?,?,0,0,'x',?)",
               (user, date, net, net, source))


def _contract(db, date, symbol, net, user=ME):
    db.execute("INSERT INTO fno_pnl_contract_daily VALUES (?,?,?,0,?,?,0,'x')",
               (user, date, symbol, net, net))


def test_session_date_does_not_invent_a_session_after_midnight():
    """Upstox's intraday book still holds the last session's positions after
    midnight. Recording those against the new calendar date wrote the same
    numbers twice and made the curve count a session that never traded."""
    from datetime import datetime

    at = lambda *a: P.session_date(datetime(*a, tzinfo=P.IST))
    assert at(2026, 8, 4, 15, 0) == "2026-08-04"   # mid-session
    assert at(2026, 8, 5, 0, 5) == "2026-08-04"    # 00:05, book is still Tuesday's
    assert at(2026, 8, 5, 8, 30) == "2026-08-04"   # pre-open
    assert at(2026, 8, 5, 9, 30) == "2026-08-05"   # opened, new session
    assert at(2026, 8, 8, 11, 0) == "2026-08-07"   # Saturday -> Friday's book


def test_snapshot_overwrites_same_day(db, monkeypatch):
    monkeypatch.setattr(P, "session_date", lambda: "2026-08-04")
    P.snapshot([{"symbol": "NIFTY26AUG24400CE", "realized": 100.0, "unrealized": 50.0, "qty": 75}], ME)
    P.snapshot([{"symbol": "NIFTY26AUG24400CE", "realized": 400.0, "unrealized": -25.0, "qty": 0}], ME)
    rows = list(db.execute("SELECT * FROM fno_pnl_daily"))
    assert len(rows) == 1
    assert (rows[0]["realized"], rows[0]["net"], rows[0]["closed_count"]) == (400.0, 375.0, 1)
    # the contract grain is upserted on the same key, not appended
    assert len(list(db.execute("SELECT * FROM fno_pnl_contract_daily"))) == 1


def test_two_users_snapshotting_the_same_session_do_not_overwrite_each_other(db, monkeypatch):
    """The day used to be the whole primary key. With two accounts that made
    every snapshot an UPSERT over somebody else's session — the second user to
    open the app would have silently replaced the first one's P&L."""
    monkeypatch.setattr(P, "session_date", lambda: "2026-08-04")
    P.snapshot([{"symbol": "NIFTY26AUG24400CE", "realized": 100.0, "unrealized": 0.0, "qty": 75}], ME)
    P.snapshot([{"symbol": "NIFTY26AUG24400CE", "realized": 999.0, "unrealized": 0.0, "qty": 75}], OTHER)

    assert P.history(ME)["stats"]["total"] == 100.0
    assert P.history(OTHER)["stats"]["total"] == 999.0
    assert len(list(db.execute("SELECT * FROM fno_pnl_daily"))) == 2
    # ...and the same contract on the same day is two rows, not one overwritten.
    assert len(list(db.execute("SELECT * FROM fno_pnl_contract_daily"))) == 2


def test_snapshot_returns_totals_even_when_the_write_fails(monkeypatch):
    """It rides along on the live positions read — a tracker write must not be
    able to take the user's book down, and the API still needs the totals."""
    monkeypatch.setattr(P, "get_connection", lambda *a, **k: 1 / 0)
    assert P.snapshot([{"symbol": "X", "realized": 10.0, "unrealized": 5.0, "qty": 1}], ME) == {
        "realized": 10.0, "unrealized": 5.0, "net": 15.0}


def test_history_never_returns_another_users_sessions(db):
    """Days, contracts, months and stats are four separate queries. All four
    have to filter, or one of them leaks the other book."""
    _day(db, "2026-08-03", 500)
    _contract(db, "2026-08-03", "NIFTY26AUG24400CE", 500)
    _day(db, "2026-06-01", 4242, user=OTHER)
    _contract(db, "2026-06-01", "SECRET26JUN100PE", 4242, user=OTHER)

    h = P.history(ME)
    assert [r["date"] for r in h["days"]] == ["2026-08-03"]
    assert [c["symbol"] for c in h["contracts"]] == ["NIFTY26AUG24400CE"]
    assert h["months"] == ["2026-08"]          # not 2026-06
    assert h["stats"]["total"] == 500

    # A user with no record of their own sees nothing, not the other book.
    assert P.history(3)["days"] == [] and P.history(3)["months"] == []


def test_history_curve_and_stats(db):
    for d, n in [("2026-08-01", 500), ("2026-08-02", -200), ("2026-08-03", -100)]:
        _day(db, d, n)
    h = P.history(ME)
    assert [r["date"] for r in h["days"]] == ["2026-08-01", "2026-08-02", "2026-08-03"]
    assert [r["cumulative"] for r in h["days"]] == [500, 300, 200]
    s = h["stats"]
    assert (s["total"], s["best"], s["worst"]) == (200, 500, -200)
    assert (s["green_days"], s["red_days"]) == (1, 2)
    assert s["win_rate"] == pytest.approx(33.3)
    assert s["streak"] == -2          # two red sessions ending today
    assert s["max_drawdown"] == -300  # 500 peak down to 200


def test_contracts_aggregate_over_the_window_and_carry_filter_fields(db):
    _day(db, "2026-08-01", 0)
    _contract(db, "2026-08-01", "NIFTY26AUG24400CE", 300)
    _contract(db, "2026-08-02", "NIFTY26AUG24400CE", 200)  # same contract, next day
    _contract(db, "2026-08-02", "BANKNIFTY26AUG52000PE", -900)
    c = P.history(ME)["contracts"]
    assert [x["symbol"] for x in c] == ["BANKNIFTY26AUG52000PE", "NIFTY26AUG24400CE"]
    assert c[1]["net"] == 500 and c[1]["sessions"] == 2
    assert (c[0]["underlying"], c[0]["right"]) == ("BANKNIFTY", "PE")
    assert (c[1]["underlying"], c[1]["right"]) == ("NIFTY", "CE")


def test_contracts_are_scoped_to_the_requested_window(db):
    _day(db, "2026-08-03", 0)  # window starts here
    _contract(db, "2026-07-01", "OLD26JUL100CE", 999)
    _contract(db, "2026-08-03", "NEW26AUG100CE", 10)
    assert [c["symbol"] for c in P.history(ME, "2026-08-03")["contracts"]] == ["NEW26AUG100CE"]


def test_history_slices_on_the_requested_month_and_lists_available_months(db):
    """The year/month filter is a date range, and `months` is what the filter
    is built from — it must offer only months the record actually has."""
    for d in ("2026-06-30", "2026-07-01", "2026-07-31", "2026-08-03"):
        _day(db, d, 100)
    h = P.history(ME, "2026-07-01", "2026-07-31")
    assert [r["date"] for r in h["days"]] == ["2026-07-01", "2026-07-31"]
    assert h["stats"]["sessions"] == 2 and h["stats"]["total"] == 200
    # the month list spans the whole record, not the slice
    assert h["months"] == ["2026-06", "2026-07", "2026-08"]


def test_flat_day_settles_nothing(db):
    _day(db, "2026-08-01", 300)
    _day(db, "2026-08-02", 0)
    s = P.history(ME)["stats"]
    assert s["win_rate"] == 100.0  # the flat day is not a loss
    assert s["streak"] == 0


def test_empty_record_reports_no_numbers(db):
    h = P.history(ME)
    assert h["contracts"] == []
    assert h["stats"]["sessions"] == 0 and h["stats"]["best"] is None
    assert h["stats"]["win_rate"] is None


def _t(date, side, qty, price, tid, scrip="NIFTY", strike="24600.0", right="CE"):
    return {"trade_date": date, "transaction_type": side, "quantity": qty, "price": price,
            "trade_id": tid, "scrip_name": scrip, "strike_price": strike,
            "option_type": right, "expiry": "2026-08-11"}


def test_fifo_books_pnl_on_the_day_the_position_closed():
    """Buy 100 @ 10 Monday, sell 100 @ 15 Tuesday: +500 belongs to Tuesday, and
    Monday books nothing — it only opened risk."""
    r = P._fifo_realized([_t("2026-08-03", "BUY", 100, 10.0, "1"),
                          _t("2026-08-04", "SELL", 100, 15.0, "2")])
    assert r == {("2026-08-04", "NIFTY 11AUG26 24600 CE"): 500.0}


def test_fifo_matches_oldest_lot_first():
    """Two lots at different prices, one partial exit — the older lot is the one
    that gets closed, so the basis is 10 (not 20, and not the average)."""
    r = P._fifo_realized([_t("2026-08-03", "BUY", 50, 10.0, "1"),
                          _t("2026-08-03", "BUY", 50, 20.0, "2"),
                          _t("2026-08-04", "SELL", 50, 30.0, "3")])
    assert r[("2026-08-04", "NIFTY 11AUG26 24600 CE")] == 1000.0  # (30-10)*50


def test_fifo_handles_shorts_and_a_reversal():
    """Sell to open 100 @ 50, buy back 150 @ 40: 100 covers the short (+1000)
    and the extra 50 opens a long, which books nothing yet."""
    r = P._fifo_realized([_t("2026-08-04", "SELL", 100, 50.0, "1"),
                          _t("2026-08-04", "BUY", 150, 40.0, "2")])
    assert r == {("2026-08-04", "NIFTY 11AUG26 24600 CE"): 1000.0}


def test_fifo_keeps_contracts_apart():
    """A call and a put on the same strike are different instruments — matching
    them against each other would invent a P&L out of two open positions."""
    r = P._fifo_realized([_t("2026-08-04", "BUY", 10, 10.0, "1", right="CE"),
                          _t("2026-08-04", "SELL", 10, 30.0, "2", right="PE")])
    assert r == {}  # both still open, nothing matched


def test_fy_chunks_never_cross_a_financial_year():
    """Upstox answers UDAPI1093 for any range that crosses 1 April."""
    from datetime import date
    assert P._fy_chunks(date(2026, 1, 15), date(2026, 8, 4)) == [
        ("2026-01-15", "2026-03-31"), ("2026-04-01", "2026-08-04")]
    assert P._fy_chunks(date(2026, 5, 1), date(2026, 8, 4)) == [("2026-05-01", "2026-08-04")]


def test_contract_parsing():
    assert P.parse_contract("NIFTY26AUG24400CE") == ("NIFTY", "CE")
    assert P.parse_contract("BANKNIFTY26AUG52000PE") == ("BANKNIFTY", "PE")
    # A future has no right — it must still resolve to its underlying rather
    # than being dropped from the filters entirely.
    assert P.parse_contract("NIFTY26AUGFUT") == ("NIFTY", None)
    assert P.parse_contract("") == ("", None)
