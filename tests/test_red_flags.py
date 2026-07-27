"""
ARTHA Terminal - Red-Flag Engine Determinism Tests
Verifies identical input always produces identical output.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engines.red_flags import RedFlagEngine, Severity


def test_pledge_high_triggers_fail():
    """Promoter pledge > 20% should trigger FAIL."""
    engine = RedFlagEngine()
    findings = engine.scan_flags_only(
        fundamentals={"pledge": 30},
        shareholding=[{"pledge_share": 30}],
    )
    flag = next((f for f in findings if f.rule_id == "PLEDGE_HIGH"), None)
    assert flag is not None
    assert flag.severity == Severity.FAIL


def test_pledge_under_threshold_passes():
    """Promoter pledge <= 20% should not flag."""
    engine = RedFlagEngine()
    findings = engine.scan_flags_only(fundamentals={}, shareholding=[{"pledge_share": 10}])
    flag = next((f for f in findings if f.rule_id == "PLEDGE_HIGH"), None)
    assert flag is None  # PASS results are filtered out


def test_ocf_pat_divergence():
    """Negative OCF + positive PAT should FAIL."""
    engine = RedFlagEngine()
    findings = engine.scan_flags_only(
        fundamentals={"ocf": -50, "pat": 100},
        shareholding=[],
    )
    flag = next((f for f in findings if f.rule_id == "OCF_PAT_DIVERGENCE"), None)
    assert flag is not None
    assert flag.severity == Severity.FAIL


def test_high_de_bfsi_exempt():
    """High D/E in BFSI sector should not trigger (sector-aware)."""
    engine = RedFlagEngine()
    findings = engine.scan_flags_only(
        fundamentals={"de_ratio": 5, "sector": "BFSI"},
        shareholding=[],
    )
    flag = next((f for f in findings if f.rule_id == "HIGH_DE"), None)
    assert flag is None


def test_high_de_non_bfsi_fails():
    """High D/E in non-BFSI should FAIL."""
    engine = RedFlagEngine()
    findings = engine.scan_flags_only(
        fundamentals={"de_ratio": 3, "sector": "IT"},
        shareholding=[],
    )
    flag = next((f for f in findings if f.rule_id == "HIGH_DE"), None)
    assert flag is not None
    assert flag.severity == Severity.FAIL


def test_determinism_same_input_same_output():
    """Identical input must produce identical output — always."""
    engine = RedFlagEngine()
    fund = {"ocf": 100, "pat": 120, "de_ratio": 1.5, "sector": "IT",
            "interest_coverage": 5, "recv_growth": 10, "rev_growth": 12}
    sh = [{"pledge_share": 5, "promoter_share": 60}]

    result1 = engine.scan(fundamentals=fund, shareholding=sh)
    result2 = engine.scan(fundamentals=fund, shareholding=sh)

    assert len(result1) == len(result2)
    for f1, f2 in zip(result1, result2):
        assert f1.severity == f2.severity
        assert f1.rule_id == f2.rule_id


def test_insufficient_data_returns_na():
    """Missing data should return NA, never a defaulted PASS/FAIL."""
    engine = RedFlagEngine()
    findings = engine.scan(fundamentals={}, shareholding=[])
    for f in findings:
        assert f.severity == Severity.NA


def test_penalty_calculation():
    """: -0.5/WARN, -1.0/FAIL."""
    engine = RedFlagEngine()
    findings = [
        type("F", (), {"severity": Severity.WARN})(),
        type("F", (), {"severity": Severity.WARN})(),
        type("F", (), {"severity": Severity.FAIL})(),
    ]
    penalty = engine.get_penalty(findings)
    assert penalty == 2.0  # 0.5 + 0.5 + 1.0


if __name__ == "__main__":
    test_pledge_high_triggers_fail()
    test_pledge_under_threshold_passes()
    test_ocf_pat_divergence()
    test_high_de_bfsi_exempt()
    test_high_de_non_bfsi_fails()
    test_determinism_same_input_same_output()
    test_insufficient_data_returns_na()
    test_penalty_calculation()
    print("✅ All red-flag engine tests passed!")