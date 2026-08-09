"""
ARTHA Terminal - data liveness reporting

The app serves the last known-good value when a feed is down. These pin the
part that makes that honest rather than misleading: the issue is reported, it
names what is being shown instead, and it carries the last-good timestamp.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import services.data_health as dh


def test_missing_membership_is_an_error_with_no_fallback_claim(monkeypatch):
    import services.constituents as c
    monkeypatch.setattr(c, "last_updated", lambda: None)

    issue = dh._check_index_members()
    assert issue["severity"] == "error"
    assert issue["last_good"] is None
    assert "hardcoded fallback" in issue["detail"]


def test_stale_membership_warns_and_reports_last_good(monkeypatch):
    import services.constituents as c
    old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    monkeypatch.setattr(c, "last_updated", lambda: old)

    issue = dh._check_index_members()
    assert issue["severity"] == "warn"
    assert issue["last_good"] == old
    assert "Serving that" in issue["detail"]


def test_fresh_membership_raises_nothing(monkeypatch):
    import services.constituents as c
    monkeypatch.setattr(c, "last_updated", lambda: datetime.now(timezone.utc).isoformat())
    assert dh._check_index_members() is None


def test_portfolio_and_market_feed_are_judged_separately(monkeypatch):
    # The expired credential is the PORTFOLIO token; the market-data token is a
    # different one. Conflating them claimed index ticks were dark while the
    # feed was streaming fine.
    import services.upstox_auth as auth
    monkeypatch.setattr(auth, "check_access_token",
                        lambda: {"status": "expired", "message": "", "name": None})
    monkeypatch.setattr(auth, "token_saved_at", lambda: "2026-07-27T09:00:00")

    issue = dh._check_upstox()
    assert issue["source"] == "upstox_portfolio"
    assert "Market data is unaffected" in issue["detail"]

    # The market-data token has to be stubbed too, or this asserts nothing on a
    # machine without one: _check_market_feed() reports the missing token before
    # it ever looks at the stream. That is why this passed locally (a real .env)
    # and failed in CI (no .env) — the test read as green while never reaching
    # the branch it was written to pin.
    from config import config
    monkeypatch.setattr(config.upstox, "analytics_token", "test-analytics-token")

    from services.upstox_stream import get_stream_manager
    monkeypatch.setattr(get_stream_manager(), "status",
                        lambda: {"started": True, "connected": True,
                                 "last_tick_age_s": 1.0, "subscribed": 5})
    assert dh._check_market_feed() is None


def test_a_missing_market_data_token_is_reported_on_its_own(monkeypatch):
    """The other half of the split above, and the state CI actually runs in."""
    from config import config
    monkeypatch.setattr(config.upstox, "analytics_token", None)

    issue = dh._check_market_feed()
    assert issue["source"] == "upstox_feed"
    assert issue["severity"] == "error"
    # Says what is served instead, rather than just declaring the feed down.
    assert "Yahoo" in issue["detail"]


class _FakeConn:
    """Answers _check_prices' two queries in order: the MAX(date)/COUNT row,
    then the count of symbols behind the target session."""

    def __init__(self, latest, total, behind):
        self._rows = [{"d": latest, "n": total}, {"n": behind}]

    def execute(self, *_a):
        row = self._rows.pop(0)
        return type("Cur", (), {"fetchone": lambda _s, r=row: r})()

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


def _prices_issue(monkeypatch, total, behind, target="2026-07-29"):
    import ingestion.quotes as q
    monkeypatch.setattr(q, "latest_trading_date", lambda: target)
    monkeypatch.setattr(dh, "get_connection",
                        lambda: _FakeConn("2026-07-29", total, behind))
    return dh._check_prices()


def test_the_delisted_tail_does_not_raise_a_permanent_warning(monkeypatch):
    # Observed live: 50 of 5005 symbols had no candle in 272 of 272 samples over
    # a whole session — delisted and suspended names that will never get one.
    # The card sat amber all day while every feed was healthy, which is how a
    # warning becomes wallpaper.
    assert _prices_issue(monkeypatch, total=5005, behind=50) is None


def test_a_real_outage_still_warns(monkeypatch):
    # A feed that actually broke takes out far more than the dead tail.
    issue = _prices_issue(monkeypatch, total=5005, behind=3000)
    assert issue["severity"] == "warn"
    assert "60%" in issue["detail"], "the share is what makes it judgeable"
    assert issue["last_good"] == "2026-07-29"


def test_threshold_boundary_is_exclusive(monkeypatch):
    # Exactly at the threshold is still the tail, not an outage.
    assert _prices_issue(monkeypatch, total=1000, behind=50) is None
    assert _prices_issue(monkeypatch, total=1000, behind=51) is not None


def test_empty_price_table_is_still_an_error(monkeypatch):
    # The threshold must not swallow the "no data at all" case.
    issue = _prices_issue(monkeypatch, total=0, behind=0)
    assert issue is None or issue["severity"] == "error"

    import ingestion.quotes as q
    monkeypatch.setattr(q, "latest_trading_date", lambda: "2026-07-29")
    monkeypatch.setattr(dh, "get_connection", lambda: _FakeConn(None, 0, 0))
    assert dh._check_prices()["severity"] == "error"


def test_errors_sort_ahead_of_warnings(monkeypatch):
    monkeypatch.setattr(dh, "_check_index_members",
                        lambda: {"source": "a", "severity": "warn", "title": "w",
                                 "detail": "", "last_good": None, "fix": None})
    monkeypatch.setattr(dh, "_check_prices",
                        lambda: {"source": "b", "severity": "error", "title": "e",
                                 "detail": "", "last_good": None, "fix": None})
    monkeypatch.setattr(dh, "_check_upstox", lambda: None)
    monkeypatch.setattr(dh, "_check_market_feed", lambda: None)
    # Both list-returning checks must be stubbed, not just the jobs one:
    # _check_stale_feeds reads the real last_good table, so a feed that happens
    # to be stale when the suite runs injects an extra warn and fails this
    # assertion. Observed in the container with pulse 2h stale.
    monkeypatch.setattr(dh, "_check_ingestion_jobs", list)
    monkeypatch.setattr(dh, "_check_stale_feeds", list)

    out = dh.get_data_health()
    assert out["live"] is False
    assert [i["severity"] for i in out["issues"]] == ["error", "warn"]


def test_a_healthy_system_reports_live(monkeypatch):
    for name in ("_check_index_members", "_check_prices", "_check_upstox", "_check_market_feed"):
        monkeypatch.setattr(dh, name, lambda: None)
    monkeypatch.setattr(dh, "_check_ingestion_jobs", list)
    monkeypatch.setattr(dh, "_check_stale_feeds", list)

    out = dh.get_data_health()
    assert out["live"] is True and out["issues"] == []
