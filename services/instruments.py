"""
ARTHA Terminal - NSE instrument index (for live symbol search / autocomplete)

Source: the Upstox instrument master (authoritative list of every NSE-listed
instrument), downloaded once and cached to the DB volume. This gives:
  • the full universe of NSE equities for the Deep-Dive dropdown (any stock), and
  • each symbol's ISIN-based instrument_key, which Upstox needs for live quotes.

Open-source / no-auth: the master is a public gzipped JSON asset.
"""

from __future__ import annotations

import gzip
import json
from datetime import datetime, timedelta

from config import config

_MASTER_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
_CACHE_FILE = config.db_path.parent / "nse_instruments.json"
_MAX_AGE_DAYS = 7

# in-process memo
_EQUITIES: list[dict] | None = None


def _download() -> list[dict]:
    """Fetch + parse the Upstox NSE master into a slim equity list."""
    import httpx

    r = httpx.get(_MASTER_URL, timeout=30.0, follow_redirects=True)
    r.raise_for_status()
    raw = json.loads(gzip.decompress(r.content))

    equities = []
    for d in raw:
        if d.get("segment") != "NSE_EQ" or d.get("instrument_type") != "EQ":
            continue
        sym = d.get("trading_symbol")
        if not sym:
            continue
        equities.append({
            "symbol": sym,
            "name": d.get("name") or d.get("short_name") or sym,
            "isin": d.get("isin"),
            "instrument_key": d.get("instrument_key"),
        })
    equities.sort(key=lambda x: x["symbol"])
    return equities


def _load_cache() -> list[dict] | None:
    try:
        if not _CACHE_FILE.exists():
            return None
        payload = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        stamp = datetime.fromisoformat(payload.get("stamp", "2000-01-01"))
        if datetime.now() - stamp > timedelta(days=_MAX_AGE_DAYS):
            return None
        return payload.get("equities") or None
    except Exception:
        return None


def _save_cache(equities: list[dict]) -> None:
    try:
        _CACHE_FILE.write_text(
            json.dumps({"stamp": datetime.now().isoformat(), "equities": equities}),
            encoding="utf-8",
        )
    except Exception:
        pass


def load_equities() -> list[dict]:
    """All NSE equities [{symbol, name, isin, instrument_key}]. Cached 7 days."""
    global _EQUITIES
    if _EQUITIES is not None:
        return _EQUITIES

    equities = _load_cache()
    if equities is None:
        try:
            equities = _download()
            _save_cache(equities)
        except Exception:
            equities = []
    _EQUITIES = equities
    return equities


def search(query: str, limit: int = 20) -> list[dict]:
    """
    Rank NSE equities for a typed query.

    Order: exact symbol → symbol prefix → symbol contains → name contains.
    """
    equities = load_equities()
    q = (query or "").strip().upper()
    if not q:
        return equities[:limit]

    exact, prefix, contains, name_hit = [], [], [], []
    for e in equities:
        sym = e["symbol"].upper()
        name = (e["name"] or "").upper()
        if sym == q:
            exact.append(e)
        elif sym.startswith(q):
            prefix.append(e)
        elif q in sym:
            contains.append(e)
        elif q in name:
            name_hit.append(e)
    ranked = exact + prefix + contains + name_hit
    return ranked[:limit]


def resolve(symbol: str) -> dict | None:
    """Instrument record for an exact NSE symbol (for the ISIN/instrument_key)."""
    q = (symbol or "").strip().upper()
    for e in load_equities():
        if e["symbol"].upper() == q:
            return e
    return None


def instrument_key(symbol: str) -> str | None:
    rec = resolve(symbol)
    return rec.get("instrument_key") if rec else None


__all__ = ["load_equities", "search", "resolve", "instrument_key"]
