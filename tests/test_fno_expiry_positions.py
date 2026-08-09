"""
ARTHA Terminal - multi-expiry selection (step 5) and read-only positions (step 6).

Two invariants worth a test each:

* an `expiry` is user input on its way to an upstream API, so an unlisted value
  must be rejected BEFORE any chain fetch — asserted by a fake client that
  records whether get_option_chain was called at all;
* the positions surface is read-only. The route rejects every write verb, and
  the Upstox client it reaches carries no order-placing method — a regression
  guard, not a formality, because "just a helper for later" is how that arrives.

No network: every Upstox call is faked.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from starlette.testclient import TestClient

from services import fno_service as svc
from services.upstox import UpstoxClient


# ----------------------------------------------------------------------
# fakes
# ----------------------------------------------------------------------

def _chain(spot=100.0, iv=12.0):
    return {"spot": spot, "strikes": [
        {"strike": 100.0, "call": {"iv": iv, "oi": 10, "ltp": 5.0},
         "put": {"iv": iv, "oi": 10, "ltp": 5.0}},
    ]}


class _FakeClient:
    """Records what was asked of it so a test can assert on the absence of a call."""
    expiries: list[str] = []
    chains: dict = {}
    asked: list[str] = []

    async def get_option_expiries(self, key):
        return list(self.expiries)

    async def get_option_chain(self, key, expiry):
        _FakeClient.asked.append(expiry)
        return self.chains.get(expiry, _chain())


def _use_fake(monkeypatch, expiries, chains=None):
    _FakeClient.expiries = expiries
    _FakeClient.chains = chains or {}
    _FakeClient.asked = []
    monkeypatch.setattr(svc, "UpstoxClient", _FakeClient)


# ----------------------------------------------------------------------
# step 5 - expiries
# ----------------------------------------------------------------------

def test_future_expiries_drops_the_expired_tail():
    from datetime import date, timedelta
    past = (date.today() - timedelta(days=30)).isoformat()
    soon = (date.today() + timedelta(days=5)).isoformat()
    far = (date.today() + timedelta(days=400)).isoformat()
    assert svc._future_expiries([past, soon, far]) == [soon, far]


def test_unlisted_expiry_is_rejected_without_fetching_a_chain(monkeypatch):
    from datetime import date, timedelta
    soon = (date.today() + timedelta(days=5)).isoformat()
    _use_fake(monkeypatch, [soon])

    res = svc.build_game_plan("nifty50", expiry="1999-01-01")

    assert res["ok"] is False
    assert "1999-01-01" in res["error"]
    assert res["expiries"] == [soon]
    # The bogus value never left the process.
    assert _FakeClient.asked == []


def test_get_expiries_reports_the_list_and_the_default(monkeypatch):
    from datetime import date, timedelta
    a = (date.today() + timedelta(days=5)).isoformat()
    b = (date.today() + timedelta(days=40)).isoformat()
    _use_fake(monkeypatch, [a, b])

    res = svc.get_expiries("nifty50")

    assert res["ok"] is True
    assert res["expiries"] == [a, b]
    assert res["default"] == a


def test_get_expiries_empty_list_is_not_ok(monkeypatch):
    _use_fake(monkeypatch, [])
    res = svc.get_expiries("nifty50")
    assert res["ok"] is False and res["expiries"] == []


# ----------------------------------------------------------------------
# step 5 - term structure
# ----------------------------------------------------------------------

def test_term_structure_caps_the_number_of_chains_fetched(monkeypatch):
    from datetime import date, timedelta
    exps = [(date.today() + timedelta(days=7 * i)).isoformat() for i in range(1, 9)]
    _use_fake(monkeypatch, exps)

    res = svc.term_structure("nifty50", n=4)

    assert res["ok"] is True and res["cap"] == 4
    assert len(res["points"]) == 4 and len(_FakeClient.asked) == 4
    assert [p["expiry"] for p in res["points"]] == exps[:4]
    assert res["complete"] is True


def test_term_structure_names_an_unpriced_expiry_and_reports_incomplete(monkeypatch):
    from datetime import date, timedelta
    exps = [(date.today() + timedelta(days=7 * i)).isoformat() for i in range(1, 4)]
    _use_fake(monkeypatch, exps, chains={
        exps[1]: {"error": "HTTP 500"},            # fetch failed
        exps[2]: _chain(iv=None),                  # ATM legs Upstox never priced
    })

    res = svc.term_structure("nifty50", n=4)

    assert [p["expiry"] for p in res["points"]] == [exps[0]]
    assert res["unpriced"] == [exps[1], exps[2]]
    # Degraded, so no caller may store it as a good 15-minute answer.
    assert res["complete"] is False
    # Nothing was invented for the missing expiries.
    assert all(p["atm_iv"] for p in res["points"])


# ----------------------------------------------------------------------
# step 6 - positions, read-only
# ----------------------------------------------------------------------

def _positions_returning(monkeypatch, payload):
    from services import upstox as up

    class _C:
        async def get_positions(self):
            return payload

    monkeypatch.setattr(up, "UpstoxClient", _C)
    from api.server import _positions
    return _positions()


def test_positions_maps_fno_rows_and_drops_everything_else(monkeypatch):
    res = _positions_returning(monkeypatch, {"status": "ok", "data": [
        {"exchange": "NFO", "trading_symbol": "NIFTY26AUG24400CE", "quantity": 75,
         "average_price": 60.0, "last_price": 68.3, "pnl": 622.5, "product": "D",
         "instrument_token": "NSE_FO|12345", "day_buy_value": 4500.0},
        {"exchange": "BFO", "trading_symbol": "SENSEX26AUG80000PE", "quantity": -20,
         "average_price": 100.0, "last_price": 90.0, "pnl": 200.0, "product": "I"},
        {"exchange": "NSE_EQ", "trading_symbol": "RELIANCE", "quantity": 10},
    ]})

    assert res["ok"] is True
    assert [i["symbol"] for i in res["items"]] == ["NIFTY26AUG24400CE", "SENSEX26AUG80000PE"]
    assert [i["side"] for i in res["items"]] == ["LONG", "SHORT"]
    # Only the display fields travel, plus the two that identify the CONTRACT.
    # realized/unrealized joined them for the P&L tracker; key/multiplier joined
    # them so the browser can put the row on the tick stream instead of watching
    # a frozen LTP between polls. Account-level fields — day_buy_value here, and
    # the ~20 others on a real row — must still not appear.
    assert set(res["items"][0]) == {"symbol", "key", "multiplier", "qty", "side",
                                    "avg", "ltp", "pnl", "realized", "unrealized",
                                    "product", "exchange"}
    assert res["items"][0]["key"] == "NSE_FO|12345"
    # Absent on the second row's payload: a missing instrument key is None, which
    # the client skips — never a stale key borrowed from another contract.
    assert res["items"][1]["key"] is None


def test_squared_off_rows_are_counted_not_listed_as_positions(monkeypatch):
    # The live book returns a row per contract traded today, net quantity 0 for
    # the ones already closed. Listing those would put 13 rows that are not
    # positions under a "positions" heading.
    res = _positions_returning(monkeypatch, {"status": "ok", "data": [
        {"exchange": "NFO", "trading_symbol": "NIFTY26AUG24400CE", "quantity": 0,
         "average_price": 60.0, "last_price": 68.3, "pnl": 12.5, "product": "D"},
        {"exchange": "NFO", "trading_symbol": "NIFTY26AUG24500CE", "quantity": 50,
         "average_price": 30.0, "last_price": 33.0, "pnl": 150.0, "product": "D"},
    ]})
    assert [i["symbol"] for i in res["items"]] == ["NIFTY26AUG24500CE"]
    assert res["closed"] == 1


def test_empty_book_is_a_real_answer_not_an_error(monkeypatch):
    res = _positions_returning(monkeypatch, {"status": "ok", "data": []})
    assert res == {"ok": True, "status": "ok", "items": [], "closed": 0,
                   "closedItems": [], "realized": 0.0, "unrealized": 0.0, "net": 0.0}


def test_squared_off_pnl_is_kept_for_the_tracker(monkeypatch):
    """A contract closed today is not an open position, but its booked P&L is
    the day's result — dropping it made the tracker report only open risk."""
    res = _positions_returning(monkeypatch, {"status": "ok", "data": [
        {"exchange": "NFO", "trading_symbol": "NIFTY26AUG24400CE", "quantity": 0,
         "average_price": 60.0, "last_price": 68.3, "pnl": 900.0,
         "realised": 900.0, "unrealised": 0.0, "product": "D"},
        {"exchange": "NFO", "trading_symbol": "NIFTY26AUG24500CE", "quantity": 50,
         "average_price": 30.0, "last_price": 33.0, "pnl": 150.0,
         "realised": 0.0, "unrealised": 150.0, "product": "D"},
    ]})
    assert res["realized"] == 900.0 and res["unrealized"] == 150.0
    assert res["net"] == 1050.0
    assert [i["symbol"] for i in res["closedItems"]] == ["NIFTY26AUG24400CE"]
    assert [i["symbol"] for i in res["items"]] == ["NIFTY26AUG24500CE"]


def test_expired_token_yields_no_items_and_a_message(monkeypatch):
    res = _positions_returning(monkeypatch, {"status": "expired", "message": "Access token expired."})
    assert res["ok"] is False and res["items"] == []
    assert res["status"] == "expired" and res["message"]


def test_positions_route_is_get_only():
    from api.server import app
    client = TestClient(app)   # not a context manager: no lifespan, no ingestion
    for method in ("post", "put", "delete", "patch"):
        assert getattr(client, method)("/api/positions").status_code == 405


def test_upstox_client_carries_no_order_capability():
    """R12 is 'read-only, no order placement, ever'. If a method whose name says
    otherwise ever lands on this client, this fails before it reaches a route."""
    suspicious = [n for n in dir(UpstoxClient)
                  if any(w in n.lower() for w in ("order", "place", "square", "cancel", "modify"))]
    assert suspicious == []


if __name__ == "__main__":  # pragma: no cover
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
