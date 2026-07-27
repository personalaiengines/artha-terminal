"""
ARTHA Terminal - One-shot Data Ingestion
Run this to populate the database with symbols, prices, and fundamentals.

Usage:
    docker compose exec artha python scripts/ingest_all.py
    or
    make ingest
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:%(name)s:%(message)s",
)

logger = logging.getLogger("ingest_all")


def main():
    print("=" * 60)
    print("  ARTHA Terminal - Data Ingestion")
    print("=" * 60)

    # Step 1: Symbols
    print("\n[1/3] Ingesting symbols...")
    from ingestion.symbol_etl import SymbolETL
    result = SymbolETL().run()
    print(f"  → {result}")

    # Step 2: Prices
    print("\n[2/3] Ingesting price candles...")
    from ingestion.price_etl import PriceETL
    result = PriceETL().run()
    print(f"  → {result}")

    # Step 3: Fundamentals
    print("\n[3/3] Ingesting fundamentals...")
    from ingestion.fundamentals_etl import FundamentalsETL
    result = FundamentalsETL().run()
    print(f"  → {result}")

    # Step 4: Compute metrics (DMA, RSI, returns, ATH/ATL)
    print("\n[4/4] Computing metrics...")
    from ingestion.compute_metrics import MetricsCalculator
    result = MetricsCalculator().run()
    print(f"  → {result}")

    # Summary
    print("\n" + "=" * 60)
    from db import get_connection

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM symbol_master")
        sym = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM prices_daily")
        prc = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM fundamentals")
        fnd = cursor.fetchone()[0]
    print(f"  ✅ Symbols:     {sym}")
    print(f"  ✅ Prices:      {prc}")
    print(f"  ✅ Fundamentals: {fnd}")
    print("=" * 60)


if __name__ == "__main__":
    main()