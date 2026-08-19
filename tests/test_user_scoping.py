"""
ARTHA Terminal — the six user-owned tables belong to exactly one account each.

The property under test is not "the list page looks right". It is:

    user B cannot read or write user A's row, including by guessing its id.

So every test here does the hostile thing on purpose — B asks for A's list by
its REAL id, deletes A's alert by its REAL id, writes into A's watchlist — and
asserts both that the call fails AND that A's row is still there afterwards. A
route that answers 200 while quietly touching nothing would pass a weaker test
and still be a bug (the client would show a deletion that never happened).

The market-data tables (prices_daily, symbol_master, fundamentals, ...) are
deliberately global and are not covered here: a close is a close whoever is
looking at it.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from starlette.testclient import TestClient

import services.auth as auth
from db import get_connection, init_database

PASSWORD = "a sufficiently long password"


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A throwaway database with the real schema + migrations, and an empty
    response cache — `api.server._cache` is process-wide and would otherwise
    carry values between tests."""
    from config import config
    import api.server as server

    init_database(tmp_path / "scope.db")
    monkeypatch.setattr(config, "db_path", tmp_path / "scope.db")
    server._cache.clear()
    return TestClient(server.app)


def _register(client, email: str) -> dict:
    r = client.post("/api/auth/register", json={"email": email, "password": PASSWORD})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture
def two_users(client):
    """A and B, in that order, so A is also the first registered user."""
    return client, _register(client, "a@example.com"), _register(client, "b@example.com")


# ---------------------------------------------------------------------------
# Watchlists
# ---------------------------------------------------------------------------
def test_watchlists_are_invisible_to_another_user(two_users):
    client, a, b = two_users
    client.post("/api/watchlists", json={"name": "A's ideas"}, headers=a)

    assert [w["name"] for w in client.get("/api/watchlists", headers=a).json()["items"]] \
        == ["A's ideas"]
    assert client.get("/api/watchlists", headers=b).json()["items"] == []


def test_b_cannot_delete_as_watchlist_by_id(two_users):
    client, a, b = two_users
    lid = client.post("/api/watchlists", json={"name": "A's ideas"}, headers=a).json()["id"]

    r = client.delete(f"/api/watchlists/{lid}", headers=b)
    # 404, not a 200 no-op: a client told "deleted" would remove the row from
    # its own view and report a success that never happened.
    assert r.status_code == 404 and r.json()["ok"] is False
    assert len(client.get("/api/watchlists", headers=a).json()["items"]) == 1

    # ...and A can still delete their own.
    assert client.delete(f"/api/watchlists/{lid}", headers=a).status_code == 200
    assert client.get("/api/watchlists", headers=a).json()["items"] == []


def test_b_cannot_write_into_as_watchlist(two_users):
    client, a, b = two_users
    lid = client.post("/api/watchlists", json={"name": "A's ideas"}, headers=a).json()["id"]
    client.post(f"/api/watchlists/{lid}/items", json={"symbol": "TCS"}, headers=a)

    assert client.post(f"/api/watchlists/{lid}/items",
                       json={"symbol": "EVIL"}, headers=b).status_code == 404
    assert client.delete(f"/api/watchlists/{lid}/items/TCS", headers=b).status_code == 404

    assert client.get("/api/watchlists", headers=a).json()["items"][0]["symbols"] == ["TCS"]
    with get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) c FROM watchlist_items "
                            "WHERE symbol='EVIL'").fetchone()["c"] == 0


def test_two_users_may_both_keep_a_list_with_the_same_name(two_users):
    """`watchlists.name` used to be globally UNIQUE. That refused the second
    user's list AND told them, by the error, that somebody else already had one
    by that name."""
    client, a, b = two_users
    assert client.post("/api/watchlists", json={"name": "Tech"}, headers=a).json()["ok"]
    assert client.post("/api/watchlists", json={"name": "Tech"}, headers=b).json()["ok"]
    # A duplicate within ONE account is still refused.
    assert client.post("/api/watchlists", json={"name": "Tech"}, headers=a).json()["ok"] is False


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------
def test_alerts_are_invisible_to_another_user_and_undeletable_by_id(two_users):
    client, a, b = two_users
    aid = client.post("/api/alerts",
                      json={"symbol": "INFY", "condition": "> 1600"}, headers=a).json()["id"]

    assert client.get("/api/alerts", headers=b).json()["items"] == []
    assert len(client.get("/api/alerts", headers=a).json()["items"]) == 1

    assert client.delete(f"/api/alerts/{aid}", headers=b).status_code == 404
    assert len(client.get("/api/alerts", headers=a).json()["items"]) == 1
    assert client.delete(f"/api/alerts/{aid}", headers=a).status_code == 200


# ---------------------------------------------------------------------------
# F&O P&L — the read AND the write path, through HTTP
# ---------------------------------------------------------------------------
def test_each_users_positions_are_recorded_and_read_back_as_their_own(two_users, monkeypatch):
    """Covers the leak that lives IN FRONT of the database as well as the one
    in it: `_cache` is process-wide, so a per-user payload stored under a plain
    "positions" key would be served to whoever asked next, and no amount of
    user_id filtering underneath would help.

    The stub reads the contextvar, so it also proves the signed-in user reaches
    the worker thread the broker call runs on.
    """
    from services import upstox as up

    class _Client:
        async def get_positions(self):
            uid = auth.current_user_id.get()
            return {"status": "ok", "data": [{
                "exchange": "NFO", "trading_symbol": f"USER{uid}26AUG100CE",
                "quantity": 75, "realised": 100.0 * uid, "unrealised": 0.0,
            }]}

    monkeypatch.setattr(up, "UpstoxClient", _Client)
    client, a, b = two_users

    pa = client.get("/api/positions", headers=a).json()
    pb = client.get("/api/positions", headers=b).json()
    assert pa["items"][0]["symbol"] == "USER126AUG100CE"
    assert pb["items"][0]["symbol"] == "USER226AUG100CE"
    assert (pa["realized"], pb["realized"]) == (100.0, 200.0)

    # Both wrote today's session. Neither sees the other's.
    ha = client.get("/api/fno/pnl", headers=a).json()
    hb = client.get("/api/fno/pnl", headers=b).json()
    assert [d["net"] for d in ha["days"]] == [100.0]
    assert [d["net"] for d in hb["days"]] == [200.0]
    assert [c["symbol"] for c in ha["contracts"]] == ["USER126AUG100CE"]
    assert [c["symbol"] for c in hb["contracts"]] == ["USER226AUG100CE"]

    # Same session date, two rows — the day alone is no longer the whole key.
    with get_connection() as conn:
        rows = conn.execute("SELECT user_id, date, net FROM fno_pnl_daily").fetchall()
    assert len(rows) == 2 and len({r["date"] for r in rows}) == 1


# ---------------------------------------------------------------------------
# Migration: shape, idempotency, and the ownership backfill
# ---------------------------------------------------------------------------
def _pre_scoping_db(path: Path) -> None:
    """A database as it looked before this migration: no user_id anywhere."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE watchlists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            created TEXT NOT NULL DEFAULT (datetime('now')));
        CREATE TABLE watchlist_items (
            list_id INTEGER NOT NULL REFERENCES watchlists(id) ON DELETE CASCADE,
            symbol TEXT NOT NULL, added TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (list_id, symbol));
        CREATE TABLE alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL,
            type TEXT NOT NULL, condition TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created TEXT NOT NULL DEFAULT (datetime('now')));
        CREATE TABLE fno_pnl_daily (
            date TEXT PRIMARY KEY, realized REAL NOT NULL DEFAULT 0,
            unrealized REAL NOT NULL DEFAULT 0, net REAL NOT NULL DEFAULT 0,
            open_count INTEGER NOT NULL DEFAULT 0,
            closed_count INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL);
        CREATE TABLE fno_pnl_contract_daily (
            date TEXT NOT NULL, symbol TEXT NOT NULL,
            realized REAL NOT NULL DEFAULT 0, unrealized REAL NOT NULL DEFAULT 0,
            net REAL NOT NULL DEFAULT 0, qty INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL, PRIMARY KEY (date, symbol));

        INSERT INTO watchlists (id, name) VALUES (1, 'My List');
        INSERT INTO watchlist_items (list_id, symbol) VALUES (1, 'TCS'), (1, 'INFY');
        INSERT INTO alerts (symbol, type, condition) VALUES ('SBIN', 'price', '> 800');
        INSERT INTO fno_pnl_daily (date, net, updated_at) VALUES ('2026-08-03', 42.0, 'x');
        INSERT INTO fno_pnl_contract_daily (date, symbol, net, updated_at)
            VALUES ('2026-08-03', 'NIFTY26AUG24400CE', 42.0, 'x');
    """)
    conn.commit()
    conn.close()


def _counts(path: Path) -> dict:
    conn = sqlite3.connect(path)
    try:
        return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in ("watchlists", "watchlist_items", "alerts",
                          "fno_pnl_daily", "fno_pnl_contract_daily")}
    finally:
        conn.close()


def test_migration_backfills_pre_auth_rows_to_the_first_user_and_is_idempotent(
        tmp_path, monkeypatch):
    from config import config
    path = tmp_path / "legacy.db"
    _pre_scoping_db(path)
    before = _counts(path)
    assert before == {"watchlists": 1, "watchlist_items": 2, "alerts": 1,
                      "fno_pnl_daily": 1, "fno_pnl_contract_daily": 1}

    # First boot: the column lands, but nobody has registered, so nothing is
    # claimed. Leaving the rows NULL is the correct answer — guessing an owner
    # that does not exist yet cannot be undone.
    init_database(path)
    monkeypatch.setattr(config, "db_path", path)
    with get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) c FROM watchlists "
                            "WHERE user_id IS NULL").fetchone()["c"] == 1

    # Someone registers, and the NEXT boot adopts the pre-auth rows.
    owner = auth.create_user("owner@example.com", PASSWORD)
    second = auth.create_user("later@example.com", PASSWORD)
    assert owner < second
    init_database(path)

    assert _counts(path) == before, "the migration must not lose or duplicate a row"
    with get_connection() as conn:
        for table in ("watchlists", "watchlist_items", "alerts",
                      "fno_pnl_daily", "fno_pnl_contract_daily"):
            owners = {r["user_id"] for r in conn.execute(f"SELECT user_id FROM {table}")}
            assert owners == {owner}, f"{table} landed on {owners}, not the first user"
        # the data itself survived the table rebuilds
        assert conn.execute("SELECT name FROM watchlists").fetchone()["name"] == "My List"
        assert conn.execute("SELECT net FROM fno_pnl_daily").fetchone()["net"] == 42.0

    # Third boot: no error, and nothing moves.
    init_database(path)
    assert _counts(path) == before
    with get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) c FROM watchlists "
                            "WHERE user_id != ?", (owner,)).fetchone()["c"] == 0


def test_the_backfill_never_claims_rows_that_already_have_an_owner(tmp_path, monkeypatch):
    """`WHERE user_id IS NULL` is the whole guard. If it ever slipped, the first
    user would inherit every other account's data on the next restart."""
    from config import config
    path = tmp_path / "owned.db"
    init_database(path)
    monkeypatch.setattr(config, "db_path", path)

    first = auth.create_user("first@example.com", PASSWORD)
    second = auth.create_user("second@example.com", PASSWORD)
    with get_connection() as conn:
        conn.execute("INSERT INTO watchlists (name, user_id) VALUES ('theirs', ?)", (second,))

    init_database(path)
    with get_connection() as conn:
        assert conn.execute("SELECT user_id FROM watchlists "
                            "WHERE name='theirs'").fetchone()["user_id"] == second
    assert first < second


def test_market_data_tables_stay_global(tmp_path):
    """Adding a user_id to prices_daily would duplicate 780k rows per account
    for no benefit. If one of these ever grows the column, it was a mistake."""
    path = tmp_path / "global.db"
    init_database(path)
    conn = sqlite3.connect(path)
    try:
        for table in ("prices_daily", "symbol_master", "fundamentals",
                      "computed_metrics", "agent_cache", "search_cache"):
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            assert cols, f"{table} is missing from the schema"
            assert "user_id" not in cols, f"{table} was scoped to a user by mistake"
    finally:
        conn.close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
