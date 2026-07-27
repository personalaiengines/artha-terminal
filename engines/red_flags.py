"""
ARTHA Terminal - Red-Flag Engine
Deterministic financial risk detection.

Rules (each a first-class, auditable object):
- PLEDGE_HIGH: Promoter pledge >20% (FAIL)
- OCF_PAT_DIVERGENCE: Negative OCF + positive PAT (FAIL)
- RECEIVABLES_SPIKE: Receivables growth >1.5x revenue growth (WARN)
- HIGH_DE: D/E >2 non-BFSI (FAIL)
- INTEREST_COVERAGE_LOW: Interest coverage <2 (WARN)
- PROMOTER_DECLINE: Promoter holding declining 3+ consecutive quarters (WARN)

Insufficient data produces NA, never a defaulted PASS/FAIL.
Identical input always produces identical output.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict
import logging

logger = logging.getLogger("engines.red_flags")


class Severity(Enum):
    """Red-flag severity levels."""
    PASS = "pass"  # No issue detected
    WARN = "warn"  # Watch-level concern
    FAIL = "fail"  # Critical concern
    NA = "na"  # Insufficient data (never a defaulted PASS/FAIL)


@dataclass
class RedFlag:
    """A single red-flag finding."""
    rule_id: str
    name: str
    severity: Severity
    message: str
    threshold: Optional[float] = None
    actual_value: Optional[float] = None
    contributing_data: Dict[str, float] = field(default_factory=dict)


@dataclass
class RedFlagRule:
    """Definition of a red-flag rule."""
    rule_id: str
    name: str
    description: str
    threshold: Optional[float]
    severity_when_triggered: Severity
    eval: callable
    message: str

    def evaluate(self, data: dict) -> RedFlag:
        """Evaluate the rule and return a RedFlag."""
        try:
            result = self.eval(data)
            if result == Severity.NA:
                return RedFlag(
                    rule_id=self.rule_id,
                    name=self.name,
                    severity=Severity.NA,
                    message=f"Insufficient data for {self.name}",
                    threshold=self.threshold,
                )
            elif result == self.severity_when_triggered:
                return RedFlag(
                    rule_id=self.rule_id,
                    name=self.name,
                    severity=self.severity_when_triggered,
                    message=self.message,
                    threshold=self.threshold,
                    actual_value=self._extract_value(data),
                )
            else:
                # Rule passed
                return RedFlag(
                    rule_id=self.rule_id,
                    name=self.name,
                    severity=Severity.PASS,
                    message="No issue detected",
                    threshold=self.threshold,
                )
        except Exception as e:
            logger.warning(f"Rule {self.rule_id} evaluation failed: {e}")
            return RedFlag(
                rule_id=self.rule_id,
                name=self.name,
                severity=Severity.NA,
                message=f"Evaluation error: {e}",
            )

    def _extract_value(self, data: dict) -> Optional[float]:
        """Extract the primary value being evaluated (for display)."""
        # Overridden per rule in config below
        return None


# ============================================
# Rule Definitions
# ============================================

def _pledge_high(data: dict) -> Severity:
    """Promoter pledge > 20% -> FAIL."""
    pledge = data.get("pledge")
    if pledge is None:
        return Severity.NA
    return Severity.FAIL if pledge > 20 else Severity.PASS


def _ocf_pat_divergence(data: dict) -> Severity:
    """Negative OCF + positive PAT -> FAIL."""
    ocf = data.get("ocf")
    pat = data.get("pat")
    if ocf is None or pat is None:
        return Severity.NA
    return Severity.FAIL if ocf < 0 and pat > 0 else Severity.PASS


def _receivables_spike(data: dict) -> Severity:
    """Receivables growth > 1.5x revenue growth -> WARN."""
    recv_growth = data.get("recv_growth")
    rev_growth = data.get("rev_growth")
    if recv_growth is None or rev_growth is None:
        return Severity.NA
    return Severity.WARN if recv_growth > 1.5 * rev_growth else Severity.PASS


def _high_de(data: dict) -> Severity:
    """D/E > 2 for non-BFSI -> FAIL."""
    de_ratio = data.get("de_ratio")
    sector = data.get("sector", "")
    if de_ratio is None:
        return Severity.NA
    # BFSI and Real Estate typically run high leverage
    if sector in ["BFSI", "Financial Services", "Banking", "NBFC", "Real Estate"]:
        return Severity.PASS
    return Severity.FAIL if de_ratio > 2 else Severity.PASS


def _interest_coverage_low(data: dict) -> Severity:
    """Interest coverage < 2 -> WARN."""
    coverage = data.get("interest_coverage")
    if coverage is None:
        return Severity.NA
    return Severity.WARN if coverage < 2 else Severity.PASS


def _promoter_decline(data: dict) -> Severity:
    """Promoter holding declining 3+ consecutive quarters -> WARN."""
    streak = data.get("promoter_decline_streak")
    if streak is None:
        return Severity.NA
    return Severity.WARN if streak >= 3 else Severity.PASS


# Rule registry - ordered list, each rule a first-class object
RULES: List[RedFlagRule] = [
    RedFlagRule(
        rule_id="PLEDGE_HIGH",
        name="High Promoter Pledge",
        description="Promoter pledged shares exceed 20% threshold",
        threshold=20.0,
        severity_when_triggered=Severity.FAIL,
        eval=_pledge_high,
        message="Promoter pledge exceeds safe threshold (>20%)",
    ),
    RedFlagRule(
        rule_id="OCF_PAT_DIVERGENCE",
        name="OCF vs PAT Mismatch",
        description="Positive PAT but negative operating cash flow",
        threshold=None,
        severity_when_triggered=Severity.FAIL,
        eval=_ocf_pat_divergence,
        message="Positive PAT but negative operating cash flow (earnings quality concern)",
    ),
    RedFlagRule(
        rule_id="RECEIVABLES_SPIKE",
        name="Receivables Growth Surge",
        description="Receivables growing faster than 1.5x revenue growth",
        threshold=1.5,
        severity_when_triggered=Severity.WARN,
        eval=_receivables_spike,
        message="Receivables growing faster than revenue (potential channel stuffing)",
    ),
    RedFlagRule(
        rule_id="HIGH_DE",
        name="High Debt-to-Equity",
        description="D/E ratio exceeds 2 for non-BFSI sector",
        threshold=2.0,
        severity_when_triggered=Severity.FAIL,
        eval=_high_de,
        message="Elevated leverage for non-BFSI sector (D/E > 2)",
    ),
    RedFlagRule(
        rule_id="INTEREST_COVERAGE_LOW",
        name="Low Interest Coverage",
        description="Interest coverage ratio below 2",
        threshold=2.0,
        severity_when_triggered=Severity.WARN,
        eval=_interest_coverage_low,
        message="Weak interest coverage ratio (<2x interest expense)",
    ),
    RedFlagRule(
        rule_id="PROMOTER_DECLINE",
        name="Declining Promoter Holding",
        description="Promoter holding declining for 3+ consecutive quarters",
        threshold=3,
        severity_when_triggered=Severity.WARN,
        eval=_promoter_decline,
        message="Promoter holding declining for 3+ consecutive quarters",
    ),
]


class RedFlagEngine:
    """
    Deterministic red-flag scanning engine.

    Pure Python - auditable, reproducible, LLM-independent.
    The LLM presents the engine's output; it cannot override it.
    """

    def __init__(self):
        self.rules = RULES

    def scan(
        self,
        fundamentals: Optional[dict] = None,
        shareholding: Optional[List[dict]] = None,
        symbol: str = None,
    ) -> List[RedFlag]:
        """
        Scan a symbol for red flags.

        Args:
            fundamentals: Dict with keys like ocf, pat, de_ratio, etc.
            shareholding: List of quarterly ownership dicts (newest first)
            symbol: Stock symbol (for logging)

        Returns:
            List of RedFlag findings (excludes PASS results)
        """
        if fundamentals is None:
            fundamentals = {}

        # Merge shareholding-derived data into the eval dict
        eval_data = dict(fundamentals)

        if shareholding and len(shareholding) > 0:
            latest = shareholding[0]
            eval_data["pledge"] = latest.get("pledge_share")
            eval_data["promoter_decline_streak"] = self._compute_promoter_decline_streak(shareholding)

        findings: List[RedFlag] = []

        for rule in self.rules:
            finding = rule.evaluate(eval_data)
            findings.append(finding)

        # Filter to only non-PASS results for the "flags" list
        # But return all findings so PASS can be reported too
        return findings

    def scan_flags_only(
        self,
        fundamentals: Optional[dict] = None,
        shareholding: Optional[List[dict]] = None,
        symbol: str = None,
    ) -> List[RedFlag]:
        """Return only triggered flags (WARN, FAIL, NA) - excludes PASS."""
        findings = self.scan(fundamentals, shareholding, symbol)
        return [f for f in findings if f.severity != Severity.PASS]

    def _compute_promoter_decline_streak(
        self,
        shareholding: List[dict],
    ) -> Optional[int]:
        """
        Count consecutive quarters of declining promoter holding.

        Args:
            shareholding: List ordered newest-first

        Returns:
            Number of consecutive declining quarters, or None if data insufficient
        """
        # Need promoter_share present in at least 4 quarters to detect a 3-streak
        promoters = [
            q.get("promoter_share") for q in shareholding
            if q.get("promoter_share") is not None
        ]

        if len(promoters) < 4:
            return None

        streak = 0
        for i in range(len(promoters) - 1):
            if promoters[i] < promoters[i + 1]:
                streak += 1
            else:
                break

        return streak

    def get_penalty(self, findings: List[RedFlag]) -> float:
        """
        Compute scorecard penalty from red flags.

        Per the build guide:
        -0.5/WARN, -1.0/FAIL (post-weighting)

        Args:
            findings: List of RedFlag findings

        Returns:
            Total penalty (always positive)
        """
        penalty = 0.0
        for f in findings:
            if f.severity == Severity.WARN:
                penalty += 0.5
            elif f.severity == Severity.FAIL:
                penalty += 1.0
        return penalty

    def get_summary(self, findings: List[RedFlag]) -> dict:
        """Get summary statistics."""
        counts = {
            "pass": 0,
            "warn": 0,
            "fail": 0,
            "na": 0,
        }
        for f in findings:
            counts[f.severity.value] += 1

        return {
            "total_rules": len(findings),
            "pass": counts["pass"],
            "warn": counts["warn"],
            "fail": counts["fail"],
            "na": counts["na"],
            "penalty": self.get_penalty(findings),
            "overall_status": (
                "CRITICAL" if counts["fail"] > 0
                else "CAUTION" if counts["warn"] > 0
                else "CLEAN" if counts["na"] == 0
                else "INCOMPLETE"
            ),
        }

    def get_rule_descriptions(self) -> List[dict]:
        """Get descriptions of all rules (for UI display)."""
        return [
            {
                "rule_id": r.rule_id,
                "name": r.name,
                "description": r.description,
                "threshold": r.threshold,
                "severity_when_triggered": r.severity_when_triggered.value,
            }
            for r in self.rules
        ]