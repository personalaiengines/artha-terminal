"""
ARTHA Terminal - Index & sector membership (read side)

Everything here comes from the `index_members` table, which
ingestion/index_members.py fills from the official NSE constituent CSVs.

This replaces services/nifty50.py, which carried hand-typed symbol lists for
NIFTY 50, Bank Nifty, Sensex and thirteen sector buckets. Those drift after
every index rejig with nothing to catch it — the hardcoded Bank Nifty shipped
already missing UNIONBANK and YESBANK.

There is no in-code fallback list by design. When the table is empty or stale
the honest answer is "this data isn't live", which services/data_health.py
reports and the UI surfaces — not a literal from 2024 dressed up as current.
"""

from __future__ import annotations

from db import get_connection

# Presentation order only — which slices lead the movers board. Membership
# itself is never defined here.
_BROAD_FIRST = ("nifty50", "banknifty", "niftynext50", "niftymidcap150")


def _rows() -> list[dict]:
    with get_connection() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT index_key, index_name, symbol, industry, updated_at FROM index_members"
        )]


def groups() -> dict[str, list[str]]:
    """{display name: [symbols]} — broad indices first, then sectors A-Z.

    Empty when the ETL has never succeeded; callers must handle that rather
    than substitute a baked-in list.
    """
    by_key: dict[str, dict] = {}
    for r in _rows():
        g = by_key.setdefault(r["index_key"], {"name": r["index_name"], "symbols": []})
        g["symbols"].append(r["symbol"])

    ordered = [k for k in _BROAD_FIRST if k in by_key]
    ordered += sorted((k for k in by_key if k not in _BROAD_FIRST),
                      key=lambda k: by_key[k]["name"])
    return {by_key[k]["name"]: by_key[k]["symbols"] for k in ordered}


def broad_universe() -> list[str]:
    """Every symbol in any tracked index — the pricing universe for movers."""
    seen: dict[str, None] = {}
    for r in _rows():
        seen.setdefault(r["symbol"], None)
    return list(seen)


def sector_map() -> dict[str, str]:
    """{symbol: NSE industry label} across every indexed stock."""
    return {r["symbol"]: r["industry"] for r in _rows() if r["industry"]}


def index_members(index_key: str) -> list[str]:
    """Symbols in one index, by key (e.g. "nifty50", "banknifty")."""
    with get_connection() as conn:
        return [r["symbol"] for r in conn.execute(
            "SELECT symbol FROM index_members WHERE index_key = ? ORDER BY symbol",
            (index_key,))]


def nifty50_sectors() -> dict[str, str]:
    """{symbol: industry} for the NIFTY 50 — what market-breadth is computed over."""
    with get_connection() as conn:
        return {r["symbol"]: r["industry"] for r in conn.execute(
            "SELECT symbol, industry FROM index_members WHERE index_key = 'nifty50'")
            if r["industry"]}


def last_updated() -> str | None:
    """Most recent successful membership write, ISO string, or None."""
    with get_connection() as conn:
        row = conn.execute("SELECT MAX(updated_at) AS t FROM index_members").fetchone()
    return row["t"] if row and row["t"] else None


__all__ = ["groups", "broad_universe", "sector_map", "index_members",
           "nifty50_sectors", "last_updated"]
