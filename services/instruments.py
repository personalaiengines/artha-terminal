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

_NSE_MASTER_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
_BSE_MASTER_URL = "https://assets.upstox.com/market-quote/instruments/exchange/BSE.json.gz"
_NSE_CACHE_FILE = config.db_path.parent / "nse_instruments.json"
_BSE_CACHE_FILE = config.db_path.parent / "bse_instruments.json"
_MAX_AGE_DAYS = 7

# BSE trading groups that represent ordinary listed equity shares. BSE's
# BSE_EQ segment also carries fixed-income/gilt/preference/fund instruments
# under the same segment tag (F, G, P, E, IF, MS, R) — excluded so "equities"
# actually means equities, not bonds.
_BSE_EQUITY_GROUPS = {"A", "B", "T", "TS", "X", "XT", "M", "MT", "Z", "ZP"}

# in-process memo
_EQUITIES: list[dict] | None = None
_BSE_EQUITIES: list[dict] | None = None


def _download(url: str, segment: str, instrument_types: set[str] | None, require_ine_isin: bool = False) -> list[dict]:
    """Fetch + parse an Upstox exchange instrument master into a slim equity list."""
    import httpx

    r = httpx.get(url, timeout=60.0, follow_redirects=True)
    r.raise_for_status()
    raw = json.loads(gzip.decompress(r.content))

    equities = []
    for d in raw:
        if d.get("segment") != segment:
            continue
        if instrument_types is not None and d.get("instrument_type") not in instrument_types:
            continue
        # BSE's equity trading groups (A/B/T/M/...) also carry mutual-fund-unit
        # ISINs (INF-prefixed) that aren't ordinary company shares — "INE" is
        # the standard prefix for actual Indian equity issuance.
        if require_ine_isin and not (d.get("isin") or "").startswith("INE"):
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


def _load_cache(cache_file) -> list[dict] | None:
    try:
        if not cache_file.exists():
            return None
        payload = json.loads(cache_file.read_text(encoding="utf-8"))
        stamp = datetime.fromisoformat(payload.get("stamp", "2000-01-01"))
        if datetime.now() - stamp > timedelta(days=_MAX_AGE_DAYS):
            return None
        return payload.get("equities") or None
    except Exception:
        return None


def _save_cache(cache_file, equities: list[dict]) -> None:
    try:
        cache_file.write_text(
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

    equities = _load_cache(_NSE_CACHE_FILE)
    if equities is None:
        try:
            equities = _download(_NSE_MASTER_URL, "NSE_EQ", {"EQ"})
            _save_cache(_NSE_CACHE_FILE, equities)
        except Exception:
            equities = []
    _EQUITIES = equities
    return equities


def load_bse_only_equities() -> list[dict]:
    """BSE-listed equities with no NSE listing (deduped by ISIN against the
    NSE master, since dual-listed companies share the same ISIN across
    exchanges) — companies visible only on BSE, mostly smaller-cap names
    NSE's own instrument master doesn't cover at all."""
    global _BSE_EQUITIES
    if _BSE_EQUITIES is not None:
        return _BSE_EQUITIES

    bse = _load_cache(_BSE_CACHE_FILE)
    if bse is None:
        try:
            bse = _download(_BSE_MASTER_URL, "BSE_EQ", _BSE_EQUITY_GROUPS, require_ine_isin=True)
            _save_cache(_BSE_CACHE_FILE, bse)
        except Exception:
            bse = []

    nse_isins = {e["isin"] for e in load_equities() if e.get("isin")}
    _BSE_EQUITIES = [e for e in bse if e.get("isin") not in nse_isins]
    return _BSE_EQUITIES


def search(query: str, limit: int = 20) -> list[dict]:
    """
    Rank NSE + BSE-only equities for a typed query.

    Order: exact symbol → symbol prefix → symbol contains → name contains.
    """
    equities = load_equities() + load_bse_only_equities()
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
    """Instrument record for an exact symbol, NSE or BSE-only (for the ISIN/instrument_key)."""
    q = (symbol or "").strip().upper()
    for e in load_equities() + load_bse_only_equities():
        if e["symbol"].upper() == q:
            return e
    return None


def instrument_key(symbol: str) -> str | None:
    rec = resolve(symbol)
    return rec.get("instrument_key") if rec else None


__all__ = ["load_equities", "load_bse_only_equities", "search", "resolve", "instrument_key"]
