"""
ARTHA Terminal - One-off company_name backfill (abbreviated -> full legal name)

symbol_master.company_name comes from Upstox's instrument master, which uses
short/abbreviated names (e.g. "CENTRAL DEPO SER (I) LTD" for CDSL, real
example: a user searched "Central Depository Services (India) Ltd" and got
no hit even though CDSL is in the DB — the substring search against the
abbreviated name never matches the full legal name). yfinance's .info has
the full legal name (longName) for the same symbol — same API call already
used by scripts/backfill_sector.py, so this reuses FundamentalsETL._yfinance_info
rather than doubling network calls with a separate fetch.

Run this AFTER scripts/backfill_sector.py finishes — do not run both against
Yahoo concurrently, that's exactly what triggered the earlier IP throttling.

Usage:
    docker compose exec api python scripts/backfill_company_name.py
"""
import sys
import time
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.WARNING)

from db import get_connection
from ingestion.fundamentals_etl import FundamentalsETL

REQUEST_DELAY = 0.6
ABORT_AFTER_CONSECUTIVE_ERRORS = 25


def main():
    with get_connection() as conn:
        rows = conn.execute("SELECT symbol, company_name FROM symbol_master").fetchall()
        symbols = [(r["symbol"], r["company_name"]) for r in rows]

    print(f"Backfilling company_name for {len(symbols)} symbols via yfinance (sequential, {REQUEST_DELAY}s/req)...")
    etl = FundamentalsETL()
    updated, unchanged, errors, error_streak = 0, 0, 0, 0

    with get_connection() as conn:
        for i, (sym, current_name) in enumerate(symbols, 1):
            try:
                info = etl._yfinance_info(sym, swallow=False) or {}
                error_streak = 0
            except Exception:
                info = {}
                errors += 1
                error_streak += 1

            full_name = info.get("longName") or info.get("shortName")
            # Only overwrite when yfinance's name is meaningfully longer — its
            # short/ETF entries are sometimes no better than Upstox's already.
            if full_name and len(full_name) > len(current_name or ""):
                conn.execute(
                    "UPDATE symbol_master SET company_name=?, updated_at=datetime('now') WHERE symbol=?",
                    (full_name, sym),
                )
                updated += 1
            else:
                unchanged += 1

            if i % 50 == 0:
                conn.commit()
                print(f"  {i}/{len(symbols)} processed ({updated} updated, {unchanged} unchanged, {errors} errors)")

            if error_streak >= ABORT_AFTER_CONSECUTIVE_ERRORS:
                conn.commit()
                print(f"Aborting: {error_streak} consecutive real errors — likely rate-limited/blocked again. "
                      f"{updated} updated so far. Retry later.")
                return

            time.sleep(REQUEST_DELAY)

        conn.commit()

    print(f"Done. {updated} updated, {unchanged} unchanged, {errors} errors.")


if __name__ == "__main__":
    main()
