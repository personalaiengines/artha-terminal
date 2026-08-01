"""
ARTHA Terminal - sector rotation stability

The heatmap changed on every refresh. Breadth picks between a live yfinance
NIFTY-50 pass and the whole DB universe depending on whether yfinance answered
— 50 stocks one poll, 3222 the next — and sector rotation was being computed
from whichever won. Different sector list, different averages, different counts,
every 180 seconds.

Sector rotation now has its own deterministic SQL source.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import services.breadth as breadth


def _rows(pairs):
    return [{"symbol": s, "sector": sec, "chg": c} for s, sec, c in pairs]


def test_sector_breadth_is_a_pure_average():
    out = breadth._sector_breadth(_rows([
        ("TCS", "Information Technology", 2.0),
        ("INFY", "Information Technology", 1.0),
        ("WIPRO", "Information Technology", -3.0),
        ("SUNPHARMA", "Pharma", 4.0),
    ]))
    it = next(s for s in out if s["sector"] == "Information Technology")
    assert it["avg_chg"] == 0.0 and it["total"] == 3 and it["advancing"] == 2
    # Best-first ordering drives the heatmap's left-to-right reading.
    assert out[0]["sector"] == "Pharma"


def test_rotation_does_not_follow_the_breadth_universe(monkeypatch):
    """The whole bug: whichever source answered breadth must not reshape the
    heatmap. Same sector input -> same sectors, regardless of breadth."""
    stable = _rows([("TCS", "Information Technology", 1.0),
                    ("INFY", "Information Technology", 3.0)])
    monkeypatch.setattr(breadth, "_sector_changes", lambda: stable)
    monkeypatch.setattr(breadth, "_live_indices", dict)
    monkeypatch.setattr(breadth, "_stock_changes",
                        lambda: _rows([("A", "Metals", 9.0)] * 3222))

    # Case 1: yfinance answers -> breadth uses the 50-stock live set.
    monkeypatch.setattr(breadth, "_nifty50_changes",
                        lambda: _rows([("X", "Energy", 1.0)] * 50))
    first = breadth.get_market_pulse()

    # Case 2: yfinance fails -> breadth falls back to 3222 DB rows.
    monkeypatch.setattr(breadth, "_nifty50_changes", list)
    second = breadth.get_market_pulse()

    assert first["sectors"] == second["sectors"]
    assert [s["sector"] for s in first["sectors"]] == ["Information Technology"]
    assert first["sectors"][0]["avg_chg"] == 2.0
    # Breadth itself is still allowed to differ — that is its documented fallback.
    assert first["breadth"]["total"] != second["breadth"]["total"]


def test_falls_back_to_breadth_rows_only_when_no_membership(monkeypatch):
    # Nothing ingested yet: better a heatmap from the breadth set than none.
    monkeypatch.setattr(breadth, "_sector_changes", list)
    monkeypatch.setattr(breadth, "_live_indices", dict)
    monkeypatch.setattr(breadth, "_nifty50_changes",
                        lambda: _rows([("X", "Energy", 1.0)] * 50))

    out = breadth.get_market_pulse()
    assert [s["sector"] for s in out["sectors"]] == ["Energy"]
