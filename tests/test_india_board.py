"""
ARTHA Terminal - Indian index board (dashboard ticker + strip)

Covers the parts that actually break: the Upstox→yfinance fallback merge, the
Gift Nifty row landing first, and NSE session state being real (a Sunday is
closed, a Wednesday mid-session is open) rather than a naive clock check.
"""

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent.parent))

from services import global_markets as gm

IST = ZoneInfo("Asia/Kolkata")


def _at(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=IST).astimezone(ZoneInfo("UTC"))


def test_nse_session_state_tracks_the_real_calendar():
    nifty = next(m for m in gm.INDIA if m.key == "nifty50")
    # Wed 2026-07-29, 11:00 IST — inside 09:15-15:30.
    assert gm.market_status(nifty, _at(2026, 7, 29, 11, 0))["state"] == "open"
    # Same day, after the close.
    assert gm.market_status(nifty, _at(2026, 7, 29, 16, 30))["state"] == "closed"
    # Sunday.
    assert gm.market_status(nifty, _at(2026, 7, 26, 11, 0))["state"] == "closed"


def test_board_falls_back_to_yfinance_for_indices_upstox_omits(monkeypatch):
    # Upstox answers for two indices and silently drops the rest — exactly what
    # it did for the (invalid) "Nifty Midcap 150" key.
    monkeypatch.setattr(gm, "_india_quotes", lambda: {
        "nifty50": {"price": 24000.0, "change_pct": 0.5},
        "sensex": {"price": 78000.0, "change_pct": -0.2},
    })
    monkeypatch.setattr(gm, "_gift_nifty_row", lambda _now: None)

    rows = gm.get_india_board(_at(2026, 7, 29, 11, 0))["indices"]

    assert [r["key"] for r in rows] == [m.key for m in gm.INDIA]
    assert rows[0]["price"] == 24000.0
    # Missing ones are still rendered, priced None — never dropped, so the grid
    # doesn't reshuffle when one feed is down.
    assert next(r for r in rows if r["key"] == "indiavix")["price"] is None
    assert all(r["status"]["state"] == "open" for r in rows)


def test_gift_nifty_leads_the_board(monkeypatch):
    monkeypatch.setattr(gm, "_india_quotes", dict)
    monkeypatch.setattr(gm, "_gift_nifty_row", lambda _now: {
        "name": "Gift Nifty", "symbol": "GIFT NIFTY", "unit": "",
        "price": 24100.0, "change_pct": 1.1,
        "status": {"state": "open", "local_time": "01:40 IST", "note": "GIFT City"},
    })

    rows = gm.get_india_board(_at(2026, 7, 29, 1, 40))["indices"]

    assert rows[0]["key"] == "giftnifty"
    assert rows[0]["price"] == 24100.0
    # Gift Nifty trades overnight — its state is its own, not the NSE session's.
    assert rows[0]["status"]["state"] == "open"
    assert rows[1]["status"]["state"] == "closed"


def test_gift_nifty_has_exactly_one_home(monkeypatch):
    # It used to be on both boards. /api/indices caches for 20s and /api/global
    # for 300s, so the topbar ticker and the Markets page showed the same
    # contract at two different prices (observed 15 points apart). One board
    # owns it; the other must not fetch it at all.
    called = []
    monkeypatch.setattr(gm, "_gift_nifty_row", lambda _now: called.append(1))
    monkeypatch.setattr(gm, "_fetch_prices",
                        lambda syms: {s: {"price": 1.0, "change_pct": 0.0} for s in syms})

    board = gm.get_global_board(_at(2026, 7, 29, 11, 0))

    assert not called, "global board must not fetch Gift Nifty"
    names = [r["name"] for r in board["indices"]]
    assert "Gift Nifty" not in names
    assert names == [m.name for m in gm.INDICES]
