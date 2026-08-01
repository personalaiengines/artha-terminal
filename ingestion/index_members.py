"""
ARTHA Terminal - Index membership ETL

Pulls the official NSE constituent CSVs into `index_members`, so index and
sector membership is ingested data rather than literals in a source file.

Why it exists:
    services/nifty50.py used to carry hand-typed lists for NIFTY 50, Bank
    Nifty, Sensex and thirteen sector buckets. They drift after every index
    rejig with nothing to catch it — the hardcoded Bank Nifty was already
    missing UNIONBANK and YESBANK on the day it shipped, so that tab silently
    under-reported two constituents.

Source:
    https://nsearchives.nseindia.com/content/indices/ind_<name>list.csv
    Columns: Company Name, Industry, Symbol, Series, ISIN Code
    The `Industry` column is NSE's own sector label, which also backfills
    symbol_master.sector for every indexed stock.

Failure behaviour (deliberate):
    An index's rows are replaced only when ITS OWN fetch succeeded. A failed
    or empty download leaves the last good membership in place — the app keeps
    serving the most recent known-good data, and services/data_health.py
    reports it as stale so the UI can say the data isn't live.

    Sensex is absent on purpose: it is a BSE index, NSE doesn't publish it, and
    api.bseindia.com redirect-loops for unauthenticated clients. Rather than
    hardcode 30 symbols that would rot, the Sensex slice is simply not offered.
"""

from __future__ import annotations

import csv
import io
import logging

import httpx

from db import get_connection

logger = logging.getLogger("ingestion.index_members")

_BASE = "https://nsearchives.nseindia.com/content/indices/ind_{}list.csv"

# index_key -> (display name, NSE csv slug). Locations of the feeds, not the
# data itself: the membership always comes from the download.
FEEDS: dict[str, tuple[str, str]] = {
    # Broad indices
    "nifty50": ("NIFTY 50", "nifty50"),
    "niftynext50": ("Nifty Next 50", "niftynext50"),
    "banknifty": ("Bank Nifty", "niftybank"),
    "niftymidcap150": ("Nifty Midcap 150", "niftymidcap150"),
    # Sector indices
    "it": ("IT", "niftyit"),
    "pharma": ("Pharma", "niftypharma"),
    "healthcare": ("Healthcare", "niftyhealthcare"),
    "auto": ("Automobile", "niftyauto"),
    "fmcg": ("FMCG", "niftyfmcg"),
    "metal": ("Metals", "niftymetal"),
    "energy": ("Energy", "niftyenergy"),
    "oilgas": ("Oil & Gas", "niftyoilgas"),
    "finance": ("Financial Services", "niftyfinance"),
    "psubank": ("PSU Banks", "niftypsubank"),
    "realty": ("Realty", "niftyrealty"),
    "infra": ("Infrastructure", "niftyinfra"),
    "consumerdurables": ("Consumer Durables", "niftyconsumerdurables"),
    "commodities": ("Commodities", "niftycommodities"),
}

_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120 Safari/537.36"),
    "Accept": "text/csv,*/*",
    "Referer": "https://www.niftyindices.com/",
}


def _fetch(client: httpx.Client, slug: str) -> list[dict]:
    """[{symbol, industry}] for one index, or [] if the download failed."""
    try:
        r = client.get(_BASE.format(slug))
        if r.status_code != 200 or not r.text.strip():
            logger.warning(f"index csv {slug}: HTTP {r.status_code}")
            return []
    except Exception as e:
        logger.warning(f"index csv {slug}: {e}")
        return []

    rows = []
    for row in csv.DictReader(io.StringIO(r.text)):
        sym = (row.get("Symbol") or "").strip().upper()
        if sym:
            rows.append({"symbol": sym, "industry": (row.get("Industry") or "").strip() or None})
    return rows


def run() -> dict:
    """Refresh every index's membership. Returns per-index counts + failures."""
    updated, failed, total = {}, [], 0

    with httpx.Client(headers=_HEADERS, timeout=15.0, follow_redirects=True) as client:
        with get_connection() as conn:
            for key, (name, slug) in FEEDS.items():
                members = _fetch(client, slug)
                if not members:
                    # Keep whatever is already stored — a bad fetch must never
                    # empty an index the app is actively serving.
                    failed.append(key)
                    continue

                conn.execute("DELETE FROM index_members WHERE index_key = ?", (key,))
                conn.executemany(
                    "INSERT INTO index_members (index_key, index_name, symbol, industry, updated_at) "
                    "VALUES (?, ?, ?, ?, datetime('now'))",
                    [(key, name, m["symbol"], m["industry"]) for m in members],
                )
                updated[key] = len(members)
                total += len(members)
            conn.commit()

    sectors = _backfill_sectors()
    result = {"status": "success" if updated else "error",
              "indices": len(updated), "members": total,
              "failed": failed, "sectors_set": sectors}
    logger.info(f"index members: {result}")
    return result


def _backfill_sectors() -> int:
    """Copy NSE's Industry label into symbol_master.sector for indexed stocks.

    symbol_master.sector is NULL for every row (the Screener scrape never
    populated it), which is why sector membership had to be hardcoded in the
    first place. This is the authoritative label, straight from the index
    provider, for the ~500 stocks that sit in some index.
    """
    with get_connection() as conn:
        cur = conn.execute("""
            UPDATE symbol_master SET sector = (
                SELECT im.industry FROM index_members im
                 WHERE im.symbol = symbol_master.symbol AND im.industry IS NOT NULL
                 LIMIT 1
            ), updated_at = datetime('now')
            WHERE EXISTS (
                SELECT 1 FROM index_members im
                 WHERE im.symbol = symbol_master.symbol AND im.industry IS NOT NULL
            )
        """)
        conn.commit()
        return cur.rowcount


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(run())
