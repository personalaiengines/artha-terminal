"""
ARTHA Terminal - Scorecard Engine
Deterministic weighted 0-10 analysis scorecard.

Five sub-scores (0-10 each):
- Valuation (25%): Inverse P/E percentile vs own 5Y + peer z-score
- Growth (25%): Blended sales + profit CAGR
- Financial Health (20%): ROE / D-E / coverage / OCF composite
- Momentum (15%): vs 200DMA + 6M return percentile
- Sector Tailwind (15%): Peer median 6M return

Red-flag penalty: -0.5/WARN, -1.0/FAIL (post-weighting)
Clamp to [0, 10].

Pure Python - LLM only presents the result, cannot override it.
Emit all sub-scores, weights, formulas, and contributing values
for full UI transparency.
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, List
from enum import Enum
import logging

from engines.red_flags import RedFlagEngine, Severity, RedFlag

logger = logging.getLogger("engines.scorecard")


@dataclass
class SubScore:
    """A single sub-score contribution."""
    name: str
    weight: float          # 0-1 (e.g., 0.25 for 25%)
    score: float           # 0-10
    formula: str           # Human-readable formula
    contributing_values: Dict[str, float] = field(default_factory=dict)


@dataclass
class Scorecard:
    """Full scorecard result."""
    symbol: str
    total_score: float                       # 0-10, clamped
    sub_scores: List[SubScore]
    red_flag_penalty: float
    raw_weighted_score: float
    red_flags: List[RedFlag]
    red_flag_summary: dict
    rating: str                              # Rating bucket (e.g., "Strong", "Weak")

    def to_dict(self) -> dict:
        """Serialize to dictionary for caching."""
        return {
            "symbol": self.symbol,
            "total_score": self.total_score,
            "raw_weighted_score": self.raw_weighted_score,
            "red_flag_penalty": self.red_flag_penalty,
            "rating": self.rating,
            "sub_scores": [
                {
                    "name": s.name,
                    "weight": s.weight,
                    "score": s.score,
                    "formula": s.formula,
                    "contributing_values": s.contributing_values,
                }
                for s in self.sub_scores
            ],
            "red_flag_summary": self.red_flag_summary,
        }


class ScorecardEngine:
    """
    Deterministic scorecard engine.

    Computes a weighted 0-10 score from five sub-scores,
    applies red-flag penalties, and clamps to [0, 10].
    """

    # Sub-score weights (must sum to 1.0)
    WEIGHTS = {
        "valuation": 0.25,
        "growth": 0.25,
        "financial_health": 0.20,
        "momentum": 0.15,
        "sector_tailwind": 0.15,
    }

    def __init__(self):
        self.red_flag_engine = RedFlagEngine()

    def compute(
        self,
        symbol: str,
        data: dict,
        fundamentals: Optional[dict] = None,
        shareholding: Optional[List[dict]] = None,
        peers: Optional[List[dict]] = None,
    ) -> Scorecard:
        """
        Compute the full scorecard.

        Args:
            symbol: Stock symbol
            data: Computed metrics dict (dma_200, returns, ath/atl, etc.)
            fundamentals: Fundamental ratios dict
            shareholding: Quarterly ownership dicts
            peers: Peer comparison data

        Returns:
            Scorecard with all sub-scores and contributing values
        """
        # Run red-flag engine first (for penalty)
        red_findings = self.red_flag_engine.scan(
            fundamentals=fundamentals or {},
            shareholding=shareholding or [],
            symbol=symbol,
        )
        red_flags = self.red_flag_engine.scan_flags_only(
            fundamentals=fundamentals or {},
            shareholding=shareholding or [],
            symbol=symbol,
        )
        red_penalty = self.red_flag_engine.get_penalty(red_findings)
        red_summary = self.red_flag_engine.get_summary(red_findings)

        # Compute each sub-score
        valuation = self._compute_valuation(data, fundamentals, peers)
        growth = self._compute_growth(fundamentals)
        health = self._compute_financial_health(fundamentals)
        momentum = self._compute_momentum(data)
        sector = self._compute_sector_tailwind(peers, data)

        sub_scores = [valuation, growth, health, momentum, sector]

        # Weighted raw score
        raw_weighted = sum(s.score * s.weight for s in sub_scores)

        # Apply penalty and clamp
        total = max(0.0, min(10.0, raw_weighted - red_penalty))

        return Scorecard(
            symbol=symbol,
            total_score=round(total, 2),
            sub_scores=sub_scores,
            red_flag_penalty=red_penalty,
            raw_weighted_score=round(raw_weighted, 2),
            red_flags=red_flags,
            red_flag_summary=red_summary,
            rating=self._rating_bucket(total),
        )

    # ============================================
    # Sub-score computations (each 0-10)
    # ============================================

    def _compute_valuation(
        self,
        data: dict,
        fundamentals: Optional[dict],
        peers: Optional[List[dict]],
    ) -> SubScore:
        """
        Valuation (25%): Inverse P/E percentile vs own 5Y + peer z-score.

        Higher score = more attractively valued (lower P/E relative to history/peers).
        """
        contributing = {}
        score = 5.0  # Default neutral

        # Component 1: P/E percentile within own 5Y history
        pe = fundamentals.get("pe_ratio") if fundamentals else None
        pe_percentile_5y = data.get("pe_percentile_5y")

        pe_component = 5.0
        if pe_percentile_5y is not None:
            # Lower percentile = cheaper vs own history -> higher score
            pe_component = max(0, min(10, 10 - (pe_percentile_5y / 10)))
            contributing["pe_percentile_5y"] = pe_percentile_5y
            contributing["pe_component"] = pe_component

        # Component 2: Peer P/E z-score
        peer_z_component = 5.0
        if peers and pe:
            peer_pes = [
                p.get("pe_ratio") for p in peers
                if p.get("pe_ratio") and p.get("pe_ratio") > 0
            ]
            if len(peer_pes) >= 3:
                import statistics
                mean_pe = statistics.mean(peer_pes)
                std_pe = statistics.stdev(peer_pes) if len(peer_pes) > 1 else 0
                if std_pe > 0:
                    z = (pe - mean_pe) / std_pe
                    # Lower z (cheaper than peers) -> higher score
                    peer_z_component = max(0, min(10, 5 - (z * 2)))
                    contributing["peer_z"] = z
                    contributing["peer_mean_pe"] = mean_pe

        if pe_percentile_5y is not None or contributing.get("peer_z") is not None:
            # Blend the two components
            score = (pe_component * 0.6) + (peer_z_component * 0.4)
        else:
            contributing["pe_ratio"] = pe or 0

        contributing["final_score"] = round(score, 2)

        return SubScore(
            name="Valuation",
            weight=self.WEIGHTS["valuation"],
            score=round(score, 2),
            formula="0.6 * (10 - pe_percentile_5y/10) + 0.4 * (5 - peer_z*2)",
            contributing_values=contributing,
        )

    def _compute_growth(self, fundamentals: Optional[dict]) -> SubScore:
        """
        Growth (25%): Blended sales + profit CAGR.

        Blends 3Y and 5Y growth rates where available.
        """
        contributing = {}
        score = 5.0  # Neutral default

        sales_3y = fundamentals.get("sales_cagr_3y") if fundamentals else None
        sales_5y = fundamentals.get("sales_cagr_5y") if fundamentals else None
        profit_3y = fundamentals.get("profit_cagr_3y") if fundamentals else None
        profit_5y = fundamentals.get("profit_cagr_5y") if fundamentals else None

        # Sales growth component (0-10)
        sales_score = 5.0
        if sales_5y is not None:
            # 20% CAGR -> near 10, 0% -> 5, -10% -> 0
            sales_score = max(0, min(10, 5 + (sales_5y / 4)))
            contributing["sales_cagr_5y"] = sales_5y
        elif sales_3y is not None:
            sales_score = max(0, min(10, 5 + (sales_3y / 3)))
            contributing["sales_cagr_3y"] = sales_3y

        # Profit growth component (0-10)
        profit_score = 5.0
        if profit_5y is not None:
            profit_score = max(0, min(10, 5 + (profit_5y / 3)))
            contributing["profit_cagr_5y"] = profit_5y
        elif profit_3y is not None:
            profit_score = max(0, min(10, 5 + (profit_3y / 2.5)))
            contributing["profit_cagr_3y"] = profit_3y

        # Blend sales (40%) and profit (60%) growth - profit growth weighted higher
        if any(k in contributing for k in [
            "sales_cagr_5y", "sales_cagr_3y",
            "profit_cagr_5y", "profit_cagr_3y"
        ]):
            score = (sales_score * 0.4) + (profit_score * 0.6)

        contributing["sales_score"] = round(sales_score, 2)
        contributing["profit_score"] = round(profit_score, 2)
        contributing["final_score"] = round(score, 2)

        return SubScore(
            name="Growth",
            weight=self.WEIGHTS["growth"],
            score=round(score, 2),
            formula="0.4 * sales_growth_score + 0.6 * profit_growth_score",
            contributing_values=contributing,
        )

    def _compute_financial_health(self, fundamentals: Optional[dict]) -> SubScore:
        """
        Financial Health (20%): ROE / D-E / coverage / OCF composite.
        """
        contributing = {}
        score = 5.0

        if not fundamentals:
            return SubScore(
                name="Financial Health",
                weight=self.WEIGHTS["financial_health"],
                score=5.0,
                formula="N/A (no fundamental data)",
                contributing_values={"final_score": 5.0},
            )

        # Component 1: ROE (Return on Equity)
        roe = fundamentals.get("roe")
        roe_score = 5.0
        if roe is not None:
            # 20% ROE -> near 10, 10% -> 6, 0% -> 2
            roe_score = max(0, min(10, 2 + (roe * 0.4)))
            contributing["roe"] = roe

        # Component 2: Debt-to-Equity (lower is better)
        de = fundamentals.get("debt_to_equity")
        de_score = 5.0
        if de is not None:
            # 0 -> 10, 1 -> 5, 2+ -> 0
            de_score = max(0, min(10, 10 - (de * 2.5)))
            contributing["debt_to_equity"] = de

        # Component 3: Interest coverage (higher is better)
        coverage = fundamentals.get("interest_coverage")
        cov_score = 5.0
        if coverage is not None:
            # <2 -> 0-2, 5x -> 6-7, 10x+ -> 10
            cov_score = max(0, min(10, min(10, coverage)
                                    if coverage < 10 else 10))
            contributing["interest_coverage"] = coverage

        # Component 4: OCF/PAT ratio (earnings quality)
        ocf = fundamentals.get("ocf")
        pat = fundamentals.get("pat")
        ocf_score = 5.0
        if ocf is not None and pat is not None and pat > 0:
            ratio = ocf / pat
            # >1.0 (OCF > PAT) -> 10, 0.5 -> 5, 0 -> 0
            ocf_score = max(0, min(10, ratio * 10))
            contributing["ocf_to_pat"] = ratio

        # Composite (equal weights for simplicity)
        scored = 0
        total_weight = 0
        for comp_score, w in [(roe_score, 0.3), (de_score, 0.3), (cov_score, 0.2), (ocf_score, 0.2)]:
            if comp_score != 5.0 or contributing.get("roe") is not None:
                scored += comp_score * w
                total_weight += w

        if total_weight > 0:
            score = scored / total_weight

        contributing["roe_score"] = round(roe_score, 2)
        contributing["de_score"] = round(de_score, 2)
        contributing["coverage_score"] = round(cov_score, 2)
        contributing["ocf_score"] = round(ocf_score, 2)
        contributing["final_score"] = round(score, 2)

        return SubScore(
            name="Financial Health",
            weight=self.WEIGHTS["financial_health"],
            score=round(score, 2),
            formula="0.3*ROE + 0.3*inv(D/E) + 0.2*coverage + 0.2*OCF/PAT",
            contributing_values=contributing,
        )

    def _compute_momentum(self, data: dict) -> SubScore:
        """
        Momentum (15%): vs 200DMA + 6M return percentile.
        """
        contributing = {}
        score = 5.0

        # Component 1: Price vs 200DMA
        dma_200 = data.get("dma_200")
        latest_price = data.get("latest_price")
        price_vs_dma = None
        if dma_200 and latest_price:
            price_vs_dma = (latest_price / dma_200) - 1
            # +20% above 200DMA -> near 10, at 200DMA -> 5, -20% below -> 0
            dma_score = max(0, min(10, 5 + (price_vs_dma * 25)))
            contributing["price_vs_200dma"] = price_vs_dma
        else:
            dma_score = 5.0

        # Component 2: 6M return percentile
        return_6m = data.get("return_6m")
        if return_6m is not None:
            # +30% in 6M -> 10, 0% -> 5, -30% -> 0
            return_score = max(0, min(10, 5 + (return_6m / 6)))
            contributing["return_6m"] = return_6m
        else:
            return_score = 5.0

        # Blend 60% 200DMA, 40% 6M return
        score = (dma_score * 0.6) + (return_score * 0.4)

        contributing["dma_score"] = round(dma_score, 2)
        contributing["return_score"] = round(return_score, 2)
        contributing["final_score"] = round(score, 2)

        return SubScore(
            name="Momentum",
            weight=self.WEIGHTS["momentum"],
            score=round(score, 2),
            formula="0.6 * (price vs 200DMA) + 0.4 * (6M return)",
            contributing_values=contributing,
        )

    def _compute_sector_tailwind(
        self,
        peers: Optional[List[dict]],
        data: dict,
    ) -> SubScore:
        """
        Sector Tailwind (15%): Peer median 6M return.

        Measures whether the sector overall is trending up.
        """
        contributing = {}
        score = 5.0

        if peers and len(peers) >= 3:
            import statistics
            peer_returns = [
                p.get("return_6m") for p in peers
                if p.get("return_6m") is not None
            ]
            if len(peer_returns) >= 3:
                median_return = statistics.median(peer_returns)
                # +30% sector -> 10, 0% -> 5, -30% -> 0
                score = max(0, min(10, 5 + (median_return / 6)))
                contributing["peer_median_return_6m"] = median_return
                contributing["peer_count"] = len(peer_returns)
                contributing["final_score"] = round(score, 2)

        return SubScore(
            name="Sector Tailwind",
            weight=self.WEIGHTS["sector_tailwind"],
            score=round(score, 2),
            formula="10 - clamp(peer_median_6M_return / 6)",
            contributing_values=contributing,
        )

    def _rating_bucket(self, score: float) -> str:
        """Convert numeric score to rating bucket."""
        if score >= 8:
            return "Strong"
        elif score >= 6.5:
            return "Favorable"
        elif score >= 5:
            return "Neutral"
        elif score >= 3.5:
            return "Cautious"
        else:
            return "Weak"

    def get_weights(self) -> dict:
        """Return the weight definitions (for UI display)."""
        return dict(self.WEIGHTS)