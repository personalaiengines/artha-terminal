"""
ARTHA Terminal - per-index / per-sector movers slices

Membership now comes from the `index_members` table (official NSE constituent
CSVs, ingested by ingestion/index_members.py). The hardcoded lists that used to
live in services/nifty50.py are gone — they shipped already missing UNIONBANK
and YESBANK from Bank Nifty.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.movers import _group_movers


def _moves(pairs):
    return [{"symbol": s, "pct": p, "price": 100.0} for s, p in pairs]


def _patch_groups(monkeypatch, mapping):
    """_group_movers imports groups() lazily, so patch it at the source module."""
    import services.constituents as c
    monkeypatch.setattr(c, "groups", lambda: mapping)


def test_splits_into_index_and_sector_buckets(monkeypatch):
    _patch_groups(monkeypatch, {"IT": ["TCS", "INFY", "WIPRO"],
                                "Bank Nifty": ["HDFCBANK", "ICICIBANK"]})
    out = _group_movers(_moves([
        ("TCS", 3.0), ("INFY", 1.0), ("WIPRO", -2.0),
        ("HDFCBANK", -0.5), ("ICICIBANK", 2.0),
    ]), top_n=5)

    assert [r["symbol"] for r in out["IT"]["gainers"]] == ["TCS", "INFY"]
    assert [r["symbol"] for r in out["IT"]["losers"]] == ["WIPRO"]
    assert out["IT"]["count"] == 3
    assert [r["symbol"] for r in out["Bank Nifty"]["gainers"]] == ["ICICIBANK"]


def test_groups_with_under_two_priced_members_are_dropped(monkeypatch):
    _patch_groups(monkeypatch, {"Pharma": ["SUNPHARMA", "CIPLA"], "IT": ["TCS", "INFY"]})
    # Only one Pharma name priced — a one-stock "sector" tab is noise.
    out = _group_movers(_moves([("SUNPHARMA", 1.0), ("TCS", 2.0), ("INFY", 1.0)]), top_n=5)
    assert "Pharma" not in out
    assert "IT" in out


def test_losers_are_ordered_worst_first(monkeypatch):
    _patch_groups(monkeypatch, {"IT": ["TCS", "INFY", "WIPRO"]})
    out = _group_movers(_moves([("TCS", -1.0), ("INFY", -4.0), ("WIPRO", -2.0)]), top_n=5)
    assert [r["symbol"] for r in out["IT"]["losers"]] == ["INFY", "WIPRO", "TCS"]
    assert out["IT"]["gainers"] == []


def test_empty_membership_yields_no_groups(monkeypatch):
    # The ETL has never run: no slices, and crucially no baked-in fallback list
    # quietly standing in for live membership. data_health reports this.
    _patch_groups(monkeypatch, {})
    assert _group_movers(_moves([("TCS", 1.0), ("INFY", 2.0)]), top_n=5) == {}


def test_no_hardcoded_membership_module_remains():
    import importlib
    try:
        importlib.import_module("services.nifty50")
    except ModuleNotFoundError:
        return
    raise AssertionError("services/nifty50.py is back — membership must come from index_members")
