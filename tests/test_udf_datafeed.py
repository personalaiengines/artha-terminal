"""UDF datafeed routes (api/udf.py).

TradingView's UDF wire format is unforgiving: column arrays not row objects, a
bare integer from /time, and `no_data` (never an empty `ok`) for a range with
no bars. Getting any of those subtly wrong produces a chart that looks like it
is working and is not.

The store is stubbed here so the suite stays hermetic - no Upstox, no live DB.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from api import udf

SENTINEL = "sk-artha-sentinel-token-must-never-be-served"

# 2026-07-31 09:15:00 IST
OPEN = 1785469500


@pytest.fixture()
def client(monkeypatch):
    """The five routes, with the data layer stubbed at its two seams."""
    bars = [{"t": OPEN + i * 60, "open": 100.0 + i, "high": 110.0 + i,
             "low": 90.0 + i, "close": 105.0 + i, "volume": 10} for i in range(10)]

    def fake_read(symbol, minutes=1, frm=0, to=None, db_path=None):
        from services.intraday import resample
        to = 10 ** 10 if to is None else to
        inside = [b for b in bars if frm <= b["t"] <= to]
        return resample(inside, minutes, now=OPEN + 10 ** 7)

    monkeypatch.setattr(udf.intraday, "read", fake_read)
    monkeypatch.setattr(udf.intraday, "neighbour_ts",
                        lambda s, frm, to, db_path=None: OPEN)
    monkeypatch.setattr(udf, "_lookup", lambda s: (
        {"symbol": udf._ticker(s), "description": "NIFTY 50", "exchange": "NSE",
         "type": "index"} if udf._ticker(s) in udf.INDEXES else None))
    monkeypatch.setattr(udf, "_search", lambda q, limit: [
        {"symbol": "NIFTY", "full_name": "NSE:NIFTY", "description": "NIFTY 50",
         "exchange": "NSE", "ticker": "NIFTY", "type": "index"}])

    # A live credential in the process. Nothing the datafeed serves may contain it.
    from config import config as cfg
    monkeypatch.setattr(cfg.upstox, "analytics_token", SENTINEL, raising=False)
    monkeypatch.setattr(cfg.upstox, "client_id", SENTINEL + "-client", raising=False)

    return TestClient(Starlette(routes=udf.routes))


def test_config_declares_the_resolutions_the_widget_needs(client):
    c = client.get("/api/udf/config").json()
    assert c["supported_resolutions"] == ["1", "5", "15", "60", "1D"]
    assert c["supports_search"] is True
    assert c["supports_time"] is True
    assert c["supports_group_request"] is False
    assert c["supports_marks"] is False


def test_time_is_a_bare_integer(client):
    r = client.get("/api/udf/time")
    assert re.fullmatch(r"\d+", r.text), r.text
    assert not r.text.startswith("{")
    assert abs(int(r.text) - __import__("time").time()) < 5


def test_symbols_describes_the_indian_session(client):
    s = client.get("/api/udf/symbols?symbol=NIFTY").json()
    assert s["ticker"] == "NIFTY"
    assert s["session"] == "0915-1530"
    assert s["timezone"] == "Asia/Kolkata"
    assert s["has_intraday"] is True
    assert s["has_empty_bars"] is False       # gaps stay gaps


def test_symbols_rejects_an_unknown_ticker(client):
    assert client.get("/api/udf/symbols?symbol=NOPE").json()["s"] == "error"


def test_history_is_column_arrays_of_equal_length(client):
    h = client.get(f"/api/udf/history?symbol=NIFTY&resolution=5"
                   f"&from={OPEN}&to={OPEN + 540}").json()
    assert h["s"] == "ok"
    n = len(h["t"])
    assert n == 2
    assert all(len(h[k]) == n for k in "ohlcv")
    assert h["t"] == sorted(set(h["t"]))              # strictly increasing
    assert all(t % 300 == 0 for t in h["t"])          # aligned to the resolution
    # first / max / min / last / sum over the five 1m bars of bucket 0
    assert (h["o"][0], h["h"][0], h["l"][0], h["c"][0], h["v"][0]) == (100, 114, 90, 109, 50)


def test_empty_range_is_no_data_with_nexttime_never_an_empty_ok(client):
    h = client.get("/api/udf/history?symbol=NIFTY&resolution=5"
                   "&from=1000000&to=1000600").json()
    assert h["s"] == "no_data"
    assert isinstance(h["nextTime"], int)
    assert "t" not in h                                # no empty ok, no fake bars


def test_bad_input_is_a_fixed_error_string(client):
    assert client.get("/api/udf/history?symbol=NIFTY&resolution=3&from=0&to=1"
                      ).json() == {"s": "error", "errmsg": "unsupported resolution"}
    assert client.get("/api/udf/history?symbol=NOPE&resolution=5&from=0&to=1"
                      ).json() == {"s": "error", "errmsg": "unknown symbol"}
    assert client.get("/api/udf/history?symbol=NIFTY&resolution=5&from=x&to=1"
                      ).json() == {"s": "error", "errmsg": "invalid range"}


@pytest.mark.needs_data
def test_search_ranks_ticker_matches_above_incidental_ones():
    """Ordering by mcap_rank was silently alphabetical - mcap_rank is NULL for
    every row in symbol_master - so "REL" returned ABREL, GILT5YBEES and
    LORENZINI APPARELS ("APPARELS" contains "rel") while RELIANCE was nowhere
    in the first page at all.

    Asserted as a ranking property, not a fixed first row: market_cap_cr is the
    tiebreak and it is populated in the live database but not in every one."""
    hits = [r["symbol"] for r in udf._search("REL", 6)]
    assert "RELIANCE" in hits
    assert all(h.startswith("REL") for h in hits)              # prefix beats substring
    assert udf._search("NIF", 3)[0]["symbol"] == "NIFTY"       # indices come first


def test_no_route_serves_a_credential(client):
    """T12 - the datafeed is market data only."""
    for url in ("/api/udf/config", "/api/udf/time", "/api/udf/symbols?symbol=NIFTY",
                "/api/udf/search?query=NIF",
                f"/api/udf/history?symbol=NIFTY&resolution=5&from={OPEN}&to={OPEN + 540}",
                "/api/udf/history?symbol=NIFTY&resolution=5&from=0&to=1",
                "/api/udf/symbols?symbol=NOPE"):
        body = client.get(url).text
        assert SENTINEL not in body, url
        assert "token" not in body.lower(), url
