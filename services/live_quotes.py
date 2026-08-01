"""
ARTHA Terminal - Live quotes via Upstox

Yahoo publishes its daily bar hours after the close, so `prices_daily` — which
is where every price in the app comes from — sat a full session behind the
user's own broker. Measured: ADANIGREEN read 1399.70 here (the 27th close)
while Upstox already had the 28th settled at 1377.80.

Upstox is the better source and was already connected:
  - authenticated, so no rate limiting (Yahoo blocked this deployment repeatedly)
  - 500 instrument keys per request, ~2.2s — the whole 5173-symbol universe in
    11 requests and about 25 seconds, versus 33 requests and 125s via Yahoo
  - carries the current session, live during market hours

Why it wasn't already used: services/upstox.py::_equity_key built keys as
`NSE_EQ|RELIANCE`, but Upstox addresses instruments by ISIN (`NSE_EQ|INE002A01018`,
as its own holdings payload shows). Every equity quote call silently returned an
empty `data` map, which read as "Upstox has no data outside market hours" and
sent the app back to Yahoo.

Yahoo remains the fallback: it covers symbols with no ISIN and works if the
Upstox token lapses.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import httpx

from config import config
from db import get_connection

logger = logging.getLogger("services.live_quotes")

BASE_URL = "https://api.upstox.com/v2"

# 500 keys/request is the measured ceiling — 1000 returns 414 URI Too Large.
CHUNK = 500

IST = timezone(timedelta(hours=5, minutes=30))
MARKET_OPEN = (9, 15)

_holidays: set[str] | None = None


def _headers() -> dict:
    return {"Authorization": f"Bearer {config.upstox.analytics_token}",
            "Accept": "application/json"}


def available() -> bool:
    return bool(config.upstox.analytics_token)


async def _holiday_dates() -> set[str]:
    """Official NSE/BSE closures, cached for the process lifetime."""
    global _holidays
    if _holidays is not None:
        return _holidays
    try:
        from services.upstox import UpstoxClient
        _holidays = {h["date"] for h in await UpstoxClient().get_market_holidays() if h.get("date")}
    except Exception as e:
        logger.warning(f"holiday calendar unavailable: {e}")
        _holidays = set()
    return _holidays


async def session_date() -> str:
    """The trading date the current quote belongs to (IST).

    Upstox's OHLC response carries no date, so stamping the candle wrong would
    silently corrupt history. Derived from the IST clock against the official
    holiday calendar rather than assumed: before the open, the live quote still
    describes the *previous* session.
    """
    now = datetime.now(IST)
    d = now.date()
    if (now.hour, now.minute) < MARKET_OPEN:
        d -= timedelta(days=1)
    holidays = await _holiday_dates()
    while d.weekday() >= 5 or d.isoformat() in holidays:
        d -= timedelta(days=1)
    return d.isoformat()


def _instrument_keys(symbols: list[str] | None = None) -> dict[str, str]:
    """{upstox_key: symbol} for symbols carrying an ISIN."""
    sql = ("SELECT symbol, isin, exchange FROM symbol_master "
           "WHERE isin IS NOT NULL AND isin != ''")
    args: tuple = ()
    if symbols:
        marks = ",".join("?" * len(symbols))
        sql += f" AND symbol IN ({marks})"
        args = tuple(s.strip().upper() for s in symbols)
    with get_connection() as conn:
        rows = conn.execute(sql, args).fetchall()
    return {
        f"{'BSE_EQ' if (r['exchange'] or '').upper() == 'BSE' else 'NSE_EQ'}|{r['isin']}": r["symbol"]
        for r in rows
    }


async def fetch_ohlc(symbols: list[str] | None = None) -> dict[str, dict]:
    """{symbol: {open, high, low, close, last_price}} for the current session."""
    if not available():
        return {}
    keys = _instrument_keys(symbols)
    if not keys:
        return {}

    out: dict[str, dict] = {}
    items = list(keys)
    async with httpx.AsyncClient(timeout=30.0) as client:
        for start in range(0, len(items), CHUNK):
            batch = items[start:start + CHUNK]
            try:
                r = await client.get(f"{BASE_URL}/market-quote/ohlc",
                                     headers=_headers(),
                                     params={"instrument_key": ",".join(batch), "interval": "1d"})
                if r.status_code != 200:
                    logger.warning(f"ohlc batch failed: HTTP {r.status_code}")
                    continue
                data = r.json().get("data") or {}
            except Exception as e:
                logger.warning(f"ohlc batch error: {e}")
                continue

            for _, v in data.items():
                # Upstox echoes a colon-form key ("NSE_EQ:TCS"), not the
                # pipe/ISIN key we sent — map back via instrument_token.
                sym = keys.get(v.get("instrument_token") or "")
                if not sym:
                    continue
                ohlc = v.get("ohlc") or {}
                last = v.get("last_price")
                close = ohlc.get("close") or last
                if not close:
                    continue  # never traded / suspended
                out[sym] = {
                    "open": ohlc.get("open") or close,
                    "high": ohlc.get("high") or close,
                    "low": ohlc.get("low") or close,
                    "close": close,
                    "last_price": last,
                }
    return out


async def refresh_async(symbols: list[str] | None = None) -> dict:
    """Write the current session's candle into prices_daily for `symbols`."""
    quotes = await fetch_ohlc(symbols)
    if not quotes:
        return {"status": "empty", "symbols": 0, "rows": 0}

    date = await session_date()
    rows = [(s, date, q["open"], q["high"], q["low"], q["close"], 0)
            for s, q in quotes.items()]

    with get_connection() as conn:
        # Volume stays 0 here: this endpoint doesn't return it, and overwriting
        # a real volume with a fake zero would be worse than leaving it out —
        # so only touch volume when the row is new.
        conn.executemany("""
            INSERT INTO prices_daily (symbol, date, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, date) DO UPDATE SET
                open = excluded.open, high = excluded.high,
                low = excluded.low, close = excluded.close
        """, rows)
        conn.commit()

    from ingestion.quotes import _refresh_day_change
    _refresh_day_change(list(quotes))
    logger.info(f"upstox refresh: {len(rows)} symbols @ {date}")
    return {"status": "success", "symbols": len(rows), "rows": len(rows), "date": date}


def refresh(symbols: list[str] | None = None) -> dict:
    """Blocking wrapper — callers are ETL jobs and thread-pool workers."""
    return asyncio.run(refresh_async(symbols))


__all__ = ["refresh", "refresh_async", "fetch_ohlc", "session_date", "available"]
