"""
ARTHA Terminal - Analysis Score ETL

Fills computed_metrics.analysis_score by batch-running the deterministic
ScorecardEngine. That column was read by api/server.py on every universe
request but written by nothing — 0 rows had a score, so the entire app fell
back to a momentum-only heuristic and called it the "AI Score".

Data-sufficiency gate (important):
    Every sub-score in ScorecardEngine defaults to 5.0 "neutral" when its
    inputs are missing. Running it over a symbol with no fundamentals
    therefore produces a confident-looking 5.0/10 built from nothing. That is
    the same fabrication this project just removed from the API layer, so we
    refuse to persist a score unless the symbol has real fundamentals AND real
    price history. Symbols that don't qualify keep analysis_score = NULL and
    fall through to the API's momentum heuristic (which is honest about being
    momentum-only, and itself returns None when there's no price data either).
"""

from __future__ import annotations

import logging
from collections import defaultdict

from db import get_connection

logger = logging.getLogger("ingestion.compute_scores")

# A scorecard is only meaningful with at least this many real fundamental
# inputs — below it, the weighted result is mostly neutral defaults.
MIN_FUNDAMENTAL_FIELDS = 2

_FUNDAMENTAL_KEYS = (
    "pe_ratio", "pb_ratio", "roe", "roce", "debt_to_equity",
    "interest_coverage", "sales_cagr_3y", "profit_cagr_3y",
    "ocf_to_pat", "current_ratio", "net_margin",
)


class ScoreETL:
    """Batch-computes analysis_score for every symbol with enough data."""

    def run(self) -> dict:
        logger.info("Starting Analysis Score ETL...")
        rows = self._load()
        if not rows:
            return {"status": "error", "error": "no computed_metrics rows", "scored": 0}

        peers_by_sector = self._peer_groups(rows)

        from engines.scorecard import ScorecardEngine
        engine = ScorecardEngine()

        scored, skipped, failed = 0, 0, 0
        updates: list[tuple[float, str]] = []

        for r in rows:
            fundamentals = {k: r[k] for k in _FUNDAMENTAL_KEYS if r.get(k) is not None}
            if not self._sufficient(r, fundamentals):
                skipped += 1
                continue
            try:
                card = engine.compute(
                    symbol=r["symbol"],
                    data=r,
                    fundamentals=fundamentals,
                    shareholding=[],  # no source wired; engine treats as neutral
                    peers=peers_by_sector.get(r.get("sector") or "", []),
                )
                updates.append((round(float(card.total_score), 2), r["symbol"]))
                scored += 1
            except Exception as e:
                logger.warning(f"Scorecard failed for {r['symbol']}: {e}")
                failed += 1

        self._write(updates)
        logger.info(f"Analysis Score ETL done: {scored} scored, {skipped} skipped, {failed} failed")
        return {"status": "success", "scored": scored, "skipped": skipped, "errors": failed}

    @staticmethod
    def _sufficient(row: dict, fundamentals: dict) -> bool:
        """Enough real inputs that the weighted score isn't mostly defaults."""
        if len(fundamentals) < MIN_FUNDAMENTAL_FIELDS:
            return False
        # Momentum needs either a 200DMA anchor or a 6M return to be real.
        has_price_signal = (
            (row.get("dma_200") is not None and row.get("latest_price") is not None)
            or row.get("return_6m") is not None
        )
        return has_price_signal

    def _load(self) -> list[dict]:
        """computed_metrics + fundamentals + latest close, in one pass."""
        with get_connection() as conn:
            rows = conn.execute("""
                SELECT cm.*,
                       COALESCE(cm.sector, m.sector) AS sector,
                       f.pe_ratio, f.pb_ratio, f.roe, f.roce, f.debt_to_equity,
                       f.interest_coverage, f.sales_cagr_3y, f.profit_cagr_3y,
                       f.ocf_to_pat, f.current_ratio, f.net_margin,
                       p.close AS latest_price
                FROM computed_metrics cm
                JOIN symbol_master m ON m.symbol = cm.symbol
                LEFT JOIN fundamentals f ON f.symbol = cm.symbol
                LEFT JOIN (
                    SELECT symbol, close FROM (
                        SELECT symbol, close,
                               ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC) rn
                        FROM prices_daily
                    ) WHERE rn = 1
                ) p ON p.symbol = cm.symbol
            """).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _peer_groups(rows: list[dict]) -> dict[str, list[dict]]:
        """Sector -> peer dicts, for the valuation/sector sub-scores."""
        groups: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            sector = r.get("sector")
            if not sector or sector == "Other":
                continue
            if r.get("pe_ratio") is None and r.get("return_6m") is None:
                continue
            groups[sector].append({
                "symbol": r["symbol"],
                "pe_ratio": r.get("pe_ratio"),
                "return_6m": r.get("return_6m"),
            })
        return groups

    @staticmethod
    def _write(updates: list[tuple[float, str]]) -> None:
        if not updates:
            return
        with get_connection() as conn:
            conn.executemany(
                "UPDATE computed_metrics SET analysis_score=?, updated_at=datetime('now') WHERE symbol=?",
                updates,
            )
            conn.commit()


__all__ = ["ScoreETL"]
