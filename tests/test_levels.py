"""Prior-session level arithmetic — pivots, CPR, Camarilla, last week's range.

Every number these produce is deterministic math on settled OHLC, so the tests
are exact rather than approximate. Textbook values are asserted by formula and
by the relationships that must hold whatever the session was (the pivot sits
inside the CPR, H3 is above L3, supports below resistances).
"""

from datetime import date

import pytest

from services.levels import _camarilla, _classic_pivots, _cpr, _prior_week_hl


# A settled session: H 24,500 · L 24,300 · C 24,450.
H, L, C = 24500.0, 24300.0, 24450.0


def test_classic_pivots_match_the_textbook_formulas():
    p = _classic_pivots(H, L, C)
    pivot = (H + L + C) / 3
    assert p["P"] == pytest.approx(pivot)
    assert p["R1"] == pytest.approx(2 * pivot - L)
    assert p["S1"] == pytest.approx(2 * pivot - H)
    assert p["R2"] == pytest.approx(pivot + (H - L))
    assert p["S2"] == pytest.approx(pivot - (H - L))
    assert p["S3"] < p["S2"] < p["S1"] < p["P"] < p["R1"] < p["R2"] < p["R3"]


def test_cpr_brackets_the_pivot_and_is_returned_top_first():
    cpr = _cpr(H, L, C)
    assert cpr["bottom"] <= cpr["P"] <= cpr["top"]
    # BC is the mid of the prior range; TC is the pivot reflected across it.
    bc = (H + L) / 2
    assert {round(cpr["top"], 6), round(cpr["bottom"], 6)} == {
        round(bc, 6), round(2 * cpr["P"] - bc, 6)}


def test_cpr_orders_its_edges_whichever_way_the_session_closed():
    """TC lands below BC on a weak close. Top must still be the top — an
    inverted band would draw resistance under support."""
    weak = _cpr(H, L, L + 1)      # close near the low
    strong = _cpr(H, L, H - 1)    # close near the high
    for cpr in (weak, strong):
        assert cpr["top"] >= cpr["bottom"]


def test_camarilla_h3_l3_straddle_the_prior_close():
    cam = _camarilla(H, L, C)
    assert cam["L3"] < C < cam["H3"]
    assert cam["H3"] == pytest.approx(C + (H - L) * 1.1 / 4)
    assert cam["L3"] == pytest.approx(C - (H - L) * 1.1 / 4)


def test_a_flat_session_collapses_every_band_onto_one_price():
    """No range means no band. The levels must coincide rather than invent width."""
    cam = _camarilla(100.0, 100.0, 100.0)
    assert cam["H3"] == cam["L3"] == 100.0
    cpr = _cpr(100.0, 100.0, 100.0)
    assert cpr["top"] == cpr["bottom"] == cpr["P"] == 100.0


class _Row(dict):
    """Enough of a pandas row for _prior_week_hl (it only reads High/Low)."""


class _Frame:
    """Minimal stand-in for the daily frame: iterrows() of (Timestamp, row)."""

    def __init__(self, rows):
        self._rows = rows

    def iterrows(self):
        return iter(self._rows)


class _Idx:
    def __init__(self, d):
        self._d = d

    def date(self):
        return self._d


def _frame(days):
    return _Frame([(_Idx(d), _Row(High=h, Low=l)) for d, h, l in days])


def test_prior_week_hl_takes_the_last_completed_week_only():
    # Mon 2026-07-20 .. Fri 2026-07-24 is the completed week; the week of
    # 2026-07-27 is the one still running when "today" is the 29th.
    hist = _frame([
        (date(2026, 7, 13), 100, 90),    # older week — must lose
        (date(2026, 7, 20), 120, 110),
        (date(2026, 7, 22), 125, 105),   # the completed week's extremes
        (date(2026, 7, 24), 118, 112),
        (date(2026, 7, 27), 200, 50),    # current week — must not count
        (date(2026, 7, 29), 210, 40),
    ])
    week = _prior_week_hl(hist, date(2026, 7, 29))
    assert week == {"high": 125.0, "low": 105.0}


def test_prior_week_hl_is_none_when_no_week_has_completed():
    hist = _frame([(date(2026, 7, 27), 200, 50), (date(2026, 7, 29), 210, 40)])
    assert _prior_week_hl(hist, date(2026, 7, 29)) is None
