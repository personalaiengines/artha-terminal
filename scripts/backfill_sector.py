"""
ARTHA Terminal - One-off sector/industry backfill

The Screener-based fundamentals ETL never successfully populated
symbol_master.sector (fragile breadcrumb scrape, plus it only ever touches
the same first 100 symbols) — every stock in the app showed sector "Other".
ingestion/fundamentals_etl.py now falls back to yfinance going forward; this
script fixes the ~2400 already-NULL rows immediately via the same source.

Yahoo blocks the container's IP after a burst of concurrent requests (seen
first-hand: 20 threads got ~800 through before a wall of 401 "Invalid Crumb"
errors, and a follow-up run at 4 threads 401'd from request #1 — the block
is IP-level, not per-process). Runs strictly sequential with a delay between
requests and bails out early on a long streak of REAL failures (connection
errors / HTTP errors) instead of burning through the rest of the list while
still blocked.

Distinct from a block: a long tail of obscure micro-cap/shell symbols that
yfinance answers successfully (HTTP 200) but simply has no sector data for
at all. That's not retryable and not a sign of throttling, so it must NOT
count toward the abort streak — only exceptions do.

Usage:
    docker compose exec api python scripts/backfill_sector.py
"""
import sys
import time
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.WARNING)

from db import get_connection
from ingestion.fundamentals_etl import FundamentalsETL

REQUEST_DELAY = 0.6  # seconds between yfinance calls — gentle enough to avoid re-triggering the block
ABORT_AFTER_CONSECUTIVE_ERRORS = 25  # real IP blocks produced hundreds/thousands of
# consecutive HTTP errors in practice — 25 real errors in a row is already a clear signal


def main():
    with get_connection() as conn:
        symbols = [r["symbol"] for r in conn.execute(
            "SELECT symbol FROM symbol_master WHERE sector IS NULL"
        ).fetchall()]

    print(f"Backfilling sector/industry for {len(symbols)} symbols via yfinance (sequential, {REQUEST_DELAY}s/req)...")
    etl = FundamentalsETL()
    updated, no_data, errors, error_streak = 0, 0, 0, 0

    with get_connection() as conn:
        for i, sym in enumerate(symbols, 1):
            try:
                sector, industry = etl._yfinance_sector_industry(sym, swallow=False)
                error_streak = 0  # call succeeded — not a block, whether or not sector came back
            except Exception:
                sector, industry = None, None
                errors += 1
                error_streak += 1

            if sector:
                conn.execute(
                    "UPDATE symbol_master SET sector=?, industry=?, updated_at=datetime('now') WHERE symbol=?",
                    (sector, industry, sym),
                )
                updated += 1
            else:
                no_data += 1

            if i % 50 == 0:
                conn.commit()
                print(f"  {i}/{len(symbols)} processed ({updated} updated, {no_data} no-data, {errors} errors)")

            if error_streak >= ABORT_AFTER_CONSECUTIVE_ERRORS:
                conn.commit()
                print(f"Aborting: {error_streak} consecutive real errors — likely rate-limited/blocked again. "
                      f"{updated} updated so far. Retry later.")
                return

            time.sleep(REQUEST_DELAY)

        conn.commit()

    print(f"Done. {updated} updated, {no_data} with no sector data in yfinance (delisted/shell/uncovered), {errors} errors.")


if __name__ == "__main__":
    main()
