"""
ARTHA Terminal - Symbol ETL
Seeds symbol_master with every NSE-listed equity, plus BSE-only equities
(companies with no NSE listing at all).

Source: services.instruments.load_equities() / load_bse_only_equities() —
the Upstox instrument masters (public, no auth, already proven reliable
elsewhere in the app for search). Previously this scraped nseindia.com
directly (blocked by anti-bot) and a BSE CSV endpoint (broken — StringIO used
without being imported), so both always failed and silently fell back to a
hardcoded ~19-symbol list. That fallback was the entire screener universe.
BSE-only names were never ingested at all, even after the NSE fix. Downstream
(price_etl, fundamentals_etl, compute_metrics) already iterate every row in
symbol_master, so fixing the seed here is enough to make the whole pipeline
cover the real market.
"""

import pandas as pd
import logging

from db import get_connection

logger = logging.getLogger("ingestion.symbol_etl")


class SymbolETL:
    """Seeds symbol_master from the full NSE + BSE-only equity instrument masters."""

    def run(self) -> dict:
        """
        Populate symbol_master with every NSE equity and every BSE-only equity.

        Returns:
            Dictionary with ETL statistics
        """
        logger.info("Starting Symbol Master ETL (Upstox NSE + BSE instrument masters)...")

        from services.instruments import load_equities, load_bse_only_equities
        nse_equities = load_equities()
        bse_equities = load_bse_only_equities()

        if not nse_equities:
            logger.error("Upstox instrument master unavailable — no symbols loaded")
            return {"status": "error", "error": "instrument master unavailable",
                    "total_symbols": 0, "errors": 1}

        rows = [{
            "symbol": e["symbol"], "company_name": e["name"], "isin": e.get("isin"),
            "exchange": "NSE", "industry": None, "sector": None,
            "market_cap_cr": None, "mcap_rank": None, "cap_segment": "Other",
            "listing_date": None,
        } for e in nse_equities] + [{
            "symbol": e["symbol"], "company_name": e["name"], "isin": e.get("isin"),
            "exchange": "BSE", "industry": None, "sector": None,
            "market_cap_cr": None, "mcap_rank": None, "cap_segment": "Other",
            "listing_date": None,
        } for e in bse_equities]

        df = pd.DataFrame(rows)
        loaded = self._load(df)
        logger.info(f"Symbol Master ETL completed: {loaded} symbols "
                    f"({len(nse_equities)} NSE, {len(bse_equities)} BSE-only)")
        return {"status": "success", "total_symbols": loaded, "errors": 0}

    def _load(self, df: pd.DataFrame) -> int:
        """Load transformed data to SQLite."""
        inserted = 0

        with get_connection() as conn:
            cursor = conn.cursor()

            for _, row in df.iterrows():
                try:
                    # Plain INSERT OR REPLACE deletes+reinserts on a symbol
                    # collision, resetting sector/industry/market_cap_cr/etc
                    # back to this seed step's placeholder None/"Other" values
                    # every time the ETL reruns — silently erasing whatever
                    # fundamentals_etl/compute_metrics had already filled in.
                    # Upsert instead: refresh only the identity columns this
                    # step actually owns, leave enrichment columns alone.
                    cursor.execute(
                        """
                        INSERT INTO symbol_master
                        (symbol, company_name, isin, exchange, industry, sector,
                         market_cap_cr, mcap_rank, cap_segment, listing_date,
                         created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                        ON CONFLICT(symbol) DO UPDATE SET
                            company_name = excluded.company_name,
                            isin = excluded.isin,
                            exchange = excluded.exchange,
                            updated_at = datetime('now')
                        """,
                        (
                            row.get("symbol"),
                            row.get("company_name"),
                            row.get("isin"),
                            row.get("exchange"),
                            row.get("industry"),
                            row.get("sector"),
                            row.get("market_cap_cr"),
                            row.get("mcap_rank"),
                            row.get("cap_segment") or "Other",
                            row.get("listing_date"),
                        ),
                    )
                    inserted += 1
                except Exception as e:
                    logger.error(f"Failed to insert symbol {row.get('symbol')}: {e}")

            conn.commit()

        return inserted

    def load_csv(self, filepath) -> dict:
        """Manually load/override symbols from a CSV with symbol/company_name/isin columns."""
        logger.info(f"Loading symbols from CSV: {filepath}")
        try:
            df = pd.read_csv(filepath)
            for col in ["symbol", "company_name", "isin", "exchange"]:
                if col not in df.columns:
                    df[col] = None
            df["exchange"] = df["exchange"].fillna("NSE")
            return {"status": "success", "loaded": self._load(df), "file": str(filepath)}
        except Exception as e:
            logger.error(f"CSV load failed: {e}")
            return {"status": "error", "error": str(e)}


__all__ = ["SymbolETL"]
