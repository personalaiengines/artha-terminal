"""
ARTHA Terminal - Global Markets service
Live international indices + commodities via Yahoo Finance, with holiday-aware
per-market open/closed status from the `exchange_calendars` library.

Data source: yfinance `fast_info` (lightweight last price + previous close).
Prices are ~15 min delayed on Yahoo — fine for an at-a-glance world board.

Market status uses real exchange calendars, so public holidays and half-days
are accounted for (unlike a naive weekday+time-window check). If the calendar
library is unavailable, we degrade to a weekday+window fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from functools import lru_cache
from zoneinfo import ZoneInfo


# ------------------------------------------------------------------
# Market definitions
# ------------------------------------------------------------------

@dataclass(frozen=True)
class Market:
    key: str
    name: str
    symbol: str            # yfinance ticker
    unit: str              # display prefix, e.g. "$"
    tz: str                # IANA timezone (for local-time display)
    cal_code: str | None   # exchange_calendars code; None = 24/7 (crypto)
    # Fallback window used only if exchange_calendars is unavailable:
    open_t: time | None = None
    close_t: time | None = None
    always_open: bool = False


INDICES: list[Market] = [
    Market("sp500", "S&P 500", "^GSPC", "", "America/New_York", "XNYS", time(9, 30), time(16, 0)),
    Market("nasdaq", "Nasdaq", "^IXIC", "", "America/New_York", "XNYS", time(9, 30), time(16, 0)),
    Market("dow", "Dow Jones", "^DJI", "", "America/New_York", "XNYS", time(9, 30), time(16, 0)),
    Market("ftse", "FTSE 100", "^FTSE", "", "Europe/London", "XLON", time(8, 0), time(16, 30)),
    Market("dax", "DAX", "^GDAXI", "", "Europe/Berlin", "XETR", time(9, 0), time(17, 30)),
    Market("nikkei", "Nikkei 225", "^N225", "", "Asia/Tokyo", "XTKS", time(9, 0), time(15, 30)),
    Market("hangseng", "Hang Seng", "^HSI", "", "Asia/Hong_Kong", "XHKG", time(9, 30), time(16, 0)),
]

# The home board. Keys match services.upstox.INDEX_KEYS so live index quotes
# come straight from the authenticated Upstox feed; the yfinance ticker is only
# the fallback for when the daily Upstox token has lapsed. XBOM is NSE/BSE's
# shared session (09:15-15:30 IST) and carries the real holiday list.
INDIA: list[Market] = [
    Market("nifty50", "Nifty 50", "^NSEI", "", "Asia/Kolkata", "XBOM", time(9, 15), time(15, 30)),
    Market("sensex", "Sensex", "^BSESN", "", "Asia/Kolkata", "XBOM", time(9, 15), time(15, 30)),
    Market("banknifty", "Bank Nifty", "^NSEBANK", "", "Asia/Kolkata", "XBOM", time(9, 15), time(15, 30)),
    Market("niftymidcap", "Nifty Midcap 50", "^NSEMDCP50", "", "Asia/Kolkata", "XBOM", time(9, 15), time(15, 30)),
    Market("indiavix", "India VIX", "^INDIAVIX", "", "Asia/Kolkata", "XBOM", time(9, 15), time(15, 30)),
]

COMMODITIES: list[Market] = [
    Market("gold", "Gold", "GC=F", "$", "America/New_York", "COMEX"),
    Market("silver", "Silver", "SI=F", "$", "America/New_York", "COMEX"),
    Market("copper", "Copper", "HG=F", "$", "America/New_York", "COMEX"),
    Market("wti", "WTI Crude", "CL=F", "$", "America/New_York", "NYMEX"),
    Market("natgas", "Natural Gas", "NG=F", "$", "America/New_York", "NYMEX"),
    Market("brent", "Brent Crude", "BZ=F", "$", "America/New_York", "NYMEX"),  # ICE; NYMEX approx
    Market("bitcoin", "Bitcoin", "BTC-USD", "$", "UTC", None, always_open=True),
]

_ALL: dict[str, Market] = {m.key: m for m in INDICES + COMMODITIES}


# ------------------------------------------------------------------
# Exchange calendars (holiday-aware)
# ------------------------------------------------------------------

@lru_cache(maxsize=None)
def _calendar(code: str):
    """Memoized exchange calendar. Returns None if unavailable."""
    try:
        import exchange_calendars as xc
        return xc.get_calendar(code)
    except Exception:
        return None


def market_status(m: Market, now_utc: datetime | None = None) -> dict:
    """
    Return {'state': 'open'|'closed', 'local_time': 'HH:MM ZZZ', 'note': str}.

    Uses the real exchange calendar (holidays + half-days included) when
    available, otherwise a weekday+window fallback.
    """
    now_utc = now_utc or datetime.now(ZoneInfo("UTC"))
    local = now_utc.astimezone(ZoneInfo(m.tz))
    local_str = local.strftime("%H:%M %Z")

    if m.always_open:
        return {"state": "open", "local_time": local_str, "note": "24/7"}

    cal = _calendar(m.cal_code) if m.cal_code else None
    if cal is not None:
        try:
            import pandas as pd
            ts = pd.Timestamp(now_utc)
            is_open = bool(cal.is_open_on_minute(ts))
            if is_open:
                nxt = cal.next_close(ts).tz_convert(m.tz)
                note = f"closes {nxt:%H:%M %Z}"
            else:
                nxt = cal.next_open(ts).tz_convert(m.tz)
                # Same calendar day but before open → "opens today"; else show date.
                note = (f"opens {nxt:%H:%M %Z}"
                        if nxt.date() == local.date()
                        else f"opens {nxt:%a %d %b}")
            return {"state": "open" if is_open else "closed",
                    "local_time": local_str, "note": note}
        except Exception:
            pass  # fall through to naive check

    # Fallback: weekday + time window (no holiday awareness)
    if m.open_t is None or m.close_t is None:
        return {"state": "open", "local_time": local_str, "note": "~24x5"}
    open_now = local.weekday() < 5 and m.open_t <= local.time() < m.close_t
    note = (f"closes {m.close_t:%H:%M}" if open_now else f"opens {m.open_t:%H:%M}")
    return {"state": "open" if open_now else "closed",
            "local_time": local_str, "note": note}


# ------------------------------------------------------------------
# Price fetch
# ------------------------------------------------------------------

def _fetch_prices(symbols: list[str]) -> dict[str, dict]:
    """Batch-fetch last price + previous close via yfinance fast_info."""
    import yfinance as yf

    out: dict[str, dict] = {}
    try:
        tickers = yf.Tickers(" ".join(symbols))
    except Exception:
        return {s: {"price": None, "change_pct": None} for s in symbols}

    for sym in symbols:
        try:
            fi = tickers.tickers[sym].fast_info
            last, prev = fi.last_price, fi.previous_close
            change_pct = ((last - prev) / prev * 100) if (last and prev) else None
            out[sym] = {"price": last, "change_pct": change_pct}
        except Exception:
            out[sym] = {"price": None, "change_pct": None}
    return out


# ------------------------------------------------------------------
# Gift Nifty (NSE IX, GIFT City) — India's overnight leading indicator.
# Not on Yahoo; sourced live from Upstox (GLOBAL_INDEX|SGX NIFTY).
# Two IST sessions: ~06:30–15:40 and 16:35–02:45 (next day), Mon–Fri.
# ------------------------------------------------------------------

def _gift_status(now_utc: datetime) -> dict:
    """Open/closed for Gift Nifty from its two IST sessions."""
    local = now_utc.astimezone(ZoneInfo("Asia/Kolkata"))
    local_str = local.strftime("%H:%M %Z")
    t, wd = local.time(), local.weekday()  # Mon=0 .. Sun=6
    s1 = time(6, 30) <= t < time(15, 40)
    s2_eve = t >= time(16, 35)
    s2_night = t < time(2, 45)
    # Sessions run Mon–Fri; the overnight tail of Fri's session ends Sat ~02:45.
    open_now = (wd < 5 and (s1 or s2_eve)) or (1 <= wd <= 5 and s2_night)
    note = "GIFT City · closes 02:45" if open_now else "GIFT City · opens 06:30"
    return {"state": "open" if open_now else "closed", "local_time": local_str, "note": note}


def _gift_nifty_row(now_utc: datetime) -> dict | None:
    """Live Gift Nifty row from Upstox, shaped like a board index row."""
    import asyncio
    from services.upstox import UpstoxClient

    async def _go():
        return await UpstoxClient().get_quote_by_keys(["GLOBAL_INDEX|SGX NIFTY"])

    try:
        loop = asyncio.new_event_loop()
        try:
            q = loop.run_until_complete(_go())
        finally:
            loop.close()
    except Exception:
        return None
    rec = (q or {}).get("SGX NIFTY")
    if not rec or rec.get("last_price") is None:
        return None
    return {
        "name": "Gift Nifty", "symbol": "GIFT NIFTY", "unit": "",
        "price": rec.get("last_price"), "change_pct": rec.get("change_pct"),
        "status": _gift_status(now_utc),
    }


def _india_quotes() -> dict[str, dict]:
    """{market_key: {price, change_pct}} for INDIA — Upstox live, yfinance fallback."""
    import asyncio
    from services.upstox import UpstoxClient

    out: dict[str, dict] = {}
    try:
        loop = asyncio.new_event_loop()
        try:
            q = loop.run_until_complete(
                UpstoxClient().get_index_quotes([m.key for m in INDIA]))
        finally:
            loop.close()
    except Exception:
        q = {}
    for key, v in (q or {}).items():
        # get_index_quotes answers {"error": "..."} when the token is gone.
        if isinstance(v, dict) and v.get("value") is not None:
            out[key] = {"price": v.get("value"), "change_pct": v.get("change")}

    missing = [m for m in INDIA if m.key not in out]
    if missing:
        prices = _fetch_prices([m.symbol for m in missing])
        for m in missing:
            p = prices.get(m.symbol) or {}
            if p.get("price") is not None:
                out[m.key] = p
    return out


def get_india_board(now_utc: datetime | None = None) -> dict:
    """Indian indices only (+ Gift Nifty), each with live price and session state.

    The dashboard strip used to render `get_global_board()` — S&P, Nasdaq, FTSE —
    on a terminal for Indian equities. This is the home board: Nifty/Sensex/Bank
    Nifty/Midcap/VIX plus Gift Nifty, the overnight lead indicator.
    """
    now_utc = now_utc or datetime.now(ZoneInfo("UTC"))
    quotes = _india_quotes()
    rows = [{
        "key": m.key, "name": m.name, "symbol": m.symbol, "unit": m.unit,
        "price": (quotes.get(m.key) or {}).get("price"),
        "change_pct": (quotes.get(m.key) or {}).get("change_pct"),
        "status": market_status(m, now_utc),
    } for m in INDIA]

    gift = _gift_nifty_row(now_utc)   # best-effort; skipped when Upstox is down
    if gift:
        rows.insert(0, {"key": "giftnifty", **gift})

    return {"indices": rows, "refreshed_at_utc": now_utc.isoformat()}


def get_global_board(now_utc: datetime | None = None) -> dict:
    """
    Assemble the board: indices + commodities with live prices and status.

    Returns {"indices": [...], "commodities": [...], "refreshed_at_utc": iso}.

    Gift Nifty deliberately does NOT appear here. It used to, and because this
    board is cached for 300s while get_india_board() is cached for 20s, the same
    contract rendered two different prices on one screen — the topbar ticker
    fresh, the Markets page up to five minutes behind. It is an Indian index;
    get_india_board() owns it.
    """
    now_utc = now_utc or datetime.now(ZoneInfo("UTC"))
    prices = _fetch_prices([m.symbol for m in _ALL.values()])

    def _rows(markets: list[Market]) -> list[dict]:
        rows = []
        for m in markets:
            p = prices.get(m.symbol, {})
            rows.append({
                "name": m.name, "symbol": m.symbol, "unit": m.unit,
                "price": p.get("price"), "change_pct": p.get("change_pct"),
                "status": market_status(m, now_utc),
            })
        return rows

    return {
        "indices": _rows(INDICES),
        "commodities": _rows(COMMODITIES),
        "refreshed_at_utc": now_utc.isoformat(),
    }


__all__ = ["Market", "INDICES", "COMMODITIES", "INDIA", "market_status",
           "get_global_board", "get_india_board"]
