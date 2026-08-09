"""Forex Factory feed mapping — the layer that makes /calendar an actual
economic calendar. Pure parse, no network."""

from datetime import date, timedelta

from services.market_events import _ff_rows, _finalize, _india_macro_rows


def _feed():
    return [
        # 2026-08-04 08:30 New York -> 18:00 IST same day.
        {"title": "CPI y/y", "country": "USD", "date": "2026-08-04T08:30:00-04:00",
         "impact": "High", "forecast": "3.1%", "previous": "3.0%"},
        # 22:00 New York -> 07:30 IST the NEXT day. The whole point of
        # normalising to IST rather than rendering the feed's own stamp.
        {"title": "Employment Change", "country": "AUD", "date": "2026-08-04T22:00:00-04:00",
         "impact": "Medium", "forecast": "", "previous": "-4.0"},
        {"title": "OPEC-JMMC Meetings", "country": "All", "date": "2026-08-05T05:15:00-04:00",
         "impact": "Holiday", "forecast": "", "previous": ""},
        {"title": "Way out of window", "country": "GBP", "date": "2027-01-04T05:15:00-04:00",
         "impact": "High", "forecast": "", "previous": ""},
        {"title": "", "country": "EUR", "date": "2026-08-05T05:15:00-04:00", "impact": "High"},
        {"title": "Unparseable date", "country": "EUR", "date": "not-a-date", "impact": "High"},
    ]


def test_ff_rows_maps_normalises_and_filters():
    start = date(2026, 8, 4)
    rows = _finalize(_ff_rows(_feed(), start, start + timedelta(days=14)))

    # Blank title, junk date and the out-of-window row are all dropped.
    assert [r["title"] for r in rows] == ["CPI y/y", "Employment Change", "OPEC-JMMC Meetings"]

    cpi = rows[0]
    assert (cpi["date"], cpi["time_ist"]) == ("2026-08-04", "18:00")
    assert (cpi["country"], cpi["impact"]) == ("USD", "high")
    assert (cpi["forecast"], cpi["previous"]) == ("3.1%", "3.0%")
    assert cpi["detail"] == "Prior 3.0%"

    # 22:00 EDT rolls into the next IST day, so it sorts after the 18:00 row.
    aud = rows[1]
    assert (aud["date"], aud["time_ist"]) == ("2026-08-05", "07:30")
    assert aud["forecast"] is None          # empty string -> None, not ""

    # "All" is cross-market, and Forex Factory's "Holiday" bucket is not a
    # fourth impact level the UI knows how to render.
    assert (rows[2]["country"], rows[2]["impact"]) == ("GLB", "low")


def test_finalize_sorts_by_time_within_the_day_and_tags_every_row():
    late = {"date": date(2026, 8, 4), "kind": "econ", "title": "Fed", "detail": "",
            "url": "u", "region": "international", "time_ist": "23:30"}
    early = {**late, "title": "PMI", "time_ist": "06:00"}
    holiday = {"date": date(2026, 8, 4), "kind": "holiday", "title": "NSE closed",
               "detail": "", "url": "u", "region": "india"}

    rows = _finalize([late, holiday, early])
    # No time_ist sorts first, then by clock — a calendar listing 23:30 above
    # 06:00 is the bug this guards.
    assert [r["title"] for r in rows] == ["NSE closed", "PMI", "Fed"]
    # Every row gets a country badge, including the deterministic ones.
    assert [r["country"] for r in rows] == ["IN", "GLB", "GLB"]


def test_rbi_repo_rate_decision_shows_on_its_day():
    """The regression this layer exists for: 2026-08-05 is MPC day 3, the repo
    rate call. It was absent because Forex Factory carries no INR."""
    d = date(2026, 8, 5)
    rows = _finalize(_india_macro_rows(d, d + timedelta(days=14)))

    mpc = [r for r in rows if r["kind"] == "policy"]
    assert len(mpc) == 1
    assert mpc[0]["date"] == "2026-08-05"
    assert mpc[0]["impact"] == "high"
    assert mpc[0]["country"] == "IN"
    assert "Aug 3-5" in mpc[0]["detail"]


def test_india_window_spans_into_next_month():
    # A window opening on the 25th must still pick up the next month's CPI on
    # the 12th — walking only the current month would silently drop it.
    rows = _india_macro_rows(date(2026, 8, 25), date(2026, 9, 20))
    titles = {r["title"] for r in rows}
    assert "India IIP" in titles          # 28 Aug, this month
    assert "India CPI inflation" in titles  # 12 Sep, next month
    assert "India GDP" in titles          # last working day of Aug (Q1)


def test_weekend_releases_roll_the_right_way():
    # Sep 2026: the 12th is a Saturday and the 14th a Monday.
    rows = _india_macro_rows(date(2026, 9, 1), date(2026, 9, 30))
    by = {r["title"]: r["date"] for r in rows}
    assert by["India CPI inflation"] == date(2026, 9, 14)  # CPI slips forward
    # Nov 2026: the 28th is a Saturday, and IIP pulls back instead.
    nov = {r["title"]: r["date"] for r in _india_macro_rows(date(2026, 11, 1), date(2026, 11, 30))}
    assert nov["India IIP"] == date(2026, 11, 27)


def test_no_india_rows_outside_the_window():
    rows = _india_macro_rows(date(2026, 8, 6), date(2026, 8, 10))
    assert all(r["kind"] != "policy" for r in rows)
