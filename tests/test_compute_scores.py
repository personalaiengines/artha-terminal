"""
ARTHA Terminal - Analysis Score ETL gate tests

The invariant under test: ScorecardEngine defaults every sub-score to 5.0
"neutral" when its inputs are missing, so running it over a symbol with no
fundamentals yields a confident-looking ~5/10 built from nothing. The ETL must
refuse to persist those, leaving analysis_score NULL so the API falls through
to its (honest) momentum heuristic instead.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ingestion.compute_scores import ScoreETL, MIN_FUNDAMENTAL_FIELDS


def test_rejects_symbol_with_no_fundamentals():
    row = {"symbol": "SHELLCO", "return_6m": 12.0, "dma_200": 100.0, "latest_price": 110.0}
    assert ScoreETL._sufficient(row, {}) is False


def test_rejects_symbol_with_too_few_fundamental_fields():
    row = {"symbol": "THIN", "return_6m": 5.0}
    assert ScoreETL._sufficient(row, {"pe_ratio": 20.0}) is False


def test_rejects_symbol_with_fundamentals_but_no_price_signal():
    # Momentum would be a pure 5.0 default with nothing to anchor it.
    row = {"symbol": "NOPRICE", "return_6m": None, "dma_200": None, "latest_price": None}
    assert ScoreETL._sufficient(row, {"pe_ratio": 20.0, "roe": 15.0}) is False


def test_accepts_symbol_with_fundamentals_and_price_signal():
    row = {"symbol": "GOODCO", "return_6m": 8.0, "dma_200": 100.0, "latest_price": 115.0}
    assert ScoreETL._sufficient(row, {"pe_ratio": 20.0, "roe": 15.0}) is True


def test_accepts_on_dma_anchor_alone_without_return():
    row = {"symbol": "DMAONLY", "return_6m": None, "dma_200": 100.0, "latest_price": 115.0}
    assert ScoreETL._sufficient(row, {"pe_ratio": 20.0, "roe": 15.0}) is True


def test_threshold_is_enforced_not_just_truthiness():
    """A single fundamental must not pass, whatever it is."""
    row = {"symbol": "ONEFIELD", "return_6m": 5.0}
    for field in ("pe_ratio", "roe", "debt_to_equity"):
        assert ScoreETL._sufficient(row, {field: 1.0}) is False
    assert MIN_FUNDAMENTAL_FIELDS >= 2


def test_peer_groups_exclude_unusable_sectors_and_empty_rows():
    rows = [
        {"symbol": "A", "sector": "IT", "pe_ratio": 20.0, "return_6m": 5.0},
        {"symbol": "B", "sector": "Other", "pe_ratio": 15.0, "return_6m": 3.0},   # bucket, not a sector
        {"symbol": "C", "sector": None, "pe_ratio": 15.0, "return_6m": 3.0},      # unknown sector
        {"symbol": "D", "sector": "IT", "pe_ratio": None, "return_6m": None},     # nothing to compare on
    ]
    groups = ScoreETL._peer_groups(rows)
    assert list(groups.keys()) == ["IT"]
    assert [p["symbol"] for p in groups["IT"]] == ["A"]
