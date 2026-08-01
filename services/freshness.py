"""
ARTHA Terminal - On-demand data freshness (lazy write-through ingestion)

Replaces the bulk nightly fundamentals crawl. Instead of a cron walking all
5173 symbols — fetching mountains of data nobody ever looks at, which is why
coverage sat at ~1% — this refreshes a symbol the moment someone actually
looks at it, writes the result to the DB, and every later viewer gets it
instantly from there. Coverage grows to match real usage.

Why this isn't just "fetch everything live, every minute":
    yfinance is the free data source and it rate-limits hard. Measured on this
    deployment: 20 concurrent threads got blocked, 4 threads got blocked, and
    even a 0.6s sequential pass eventually drew a wall of HTTP 401 "Invalid
    Crumb" responses. A 1-minute full-universe refresh is ~86 req/s sustained
    and would earn a permanent IP block. So the fetch has to be bounded to
    what's on screen — which is exactly what a page view gives us.

The refresh runs in the background: the caller never waits on the network. The
request serves whatever the DB has now, and the fresh value lands for the next
render.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from db import get_connection

logger = logging.getLogger("services.freshness")

# How long before re-attempting a symbol whose price didn't advance. Yahoo
# publishes the daily bar hours after the close, so a symbol legitimately reads
# "behind" for a long stretch with nothing to fetch.
PRICE_RETRY_SECONDS = 30 * 60
_px_attempted: dict[str, float] = {}

# Fundamentals (P/E, ROE, market cap) move on results/price, not by the minute.
# A day old is fine; anything older gets refetched when someone views it.
MAX_AGE_HOURS = 24

# Bounded so one page view can't fan out into a rate-limit trip. A table shows
# a screenful; this is comfortably above that.
MAX_PER_REQUEST = 60

_POOL = ThreadPoolExecutor(max_workers=3, thread_name_prefix="freshness")
_inflight: set[str] = set()
_lock = threading.Lock()


def stale_symbols(symbols: list[str], max_age_hours: int = MAX_AGE_HOURS) -> list[str]:
    """Which of these have missing or out-of-date fundamentals."""
    symbols = [s.strip().upper() for s in symbols if s and s.strip()]
    if not symbols:
        return []
    cutoff = (datetime.now() - timedelta(hours=max_age_hours)).strftime("%Y-%m-%d")
    marks = ",".join("?" * len(symbols))
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT symbol, date_updated FROM fundamentals WHERE symbol IN ({marks})",
            tuple(symbols),
        ).fetchall()
    known = {r["symbol"]: r["date_updated"] for r in rows}
    return [s for s in symbols
            if s not in known or not known[s] or known[s] < cutoff]


def stale_prices(symbols: list[str]) -> list[str]:
    """Which of these have no candle for the latest trading day we know of.

    Prices go stale far faster than fundamentals and they're what the user
    actually reads off every screen, so they get their own (much tighter)
    check rather than sharing the 24h fundamentals window.
    """
    symbols = [s.strip().upper() for s in symbols if s and s.strip()]
    if not symbols:
        return []
    from ingestion.quotes import latest_trading_date
    target = latest_trading_date()
    if not target:
        return []
    marks = ",".join("?" * len(symbols))
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT symbol, MAX(date) d FROM prices_daily WHERE symbol IN ({marks}) "
            f"GROUP BY symbol", tuple(symbols)).fetchall()
    current = {r["symbol"] for r in rows if r["d"] and r["d"] >= target}
    return [s for s in symbols if s not in current]


def refresh_prices_async(symbols: list[str]) -> dict:
    """Queue a batched price refresh for whichever of `symbols` are behind.

    One batched request covers up to 100 symbols, so unlike the fundamentals
    path this is cheap enough to run on every page view.
    """
    stale = stale_prices(symbols)[:MAX_PER_REQUEST]
    if not stale:
        return {"queued": 0, "stale": 0}

    # A symbol stays "stale" until the upstream actually publishes the bar, and
    # Yahoo lags the close by hours. Without this cooldown every page view
    # re-queues the same symbols that just came back empty — turning the
    # on-view refresh into a rate-limit generator against the one source the
    # whole app depends on.
    now = time.time()
    with _lock:
        fresh_attempt = [s for s in stale if now - _px_attempted.get(s, 0) < PRICE_RETRY_SECONDS]
        todo = [s for s in stale
                if s not in fresh_attempt and f"px:{s}" not in _inflight]
        _inflight.update(f"px:{s}" for s in todo)
        _px_attempted.update({s: now for s in todo})
    if not todo:
        return {"queued": 0, "stale": len(stale), "cooling": len(fresh_attempt)}

    def work():
        try:
            from ingestion.quotes import refresh_best, tracked_symbols
            known = {t["symbol"]: t for t in tracked_symbols()}
            targets = [known.get(s) or {"symbol": s, "exchange": "NSE"} for s in todo]
            refresh_best(targets)
        except Exception as e:
            logger.warning(f"on-demand price refresh failed: {e}")
        finally:
            with _lock:
                _inflight.difference_update(f"px:{s}" for s in todo)

    _POOL.submit(work)
    return {"queued": len(todo), "stale": len(stale)}


def refresh_async(symbols: list[str], max_age_hours: int = MAX_AGE_HOURS) -> dict:
    """Queue a background refresh for whichever of `symbols` are stale.

    Returns immediately — the caller serves current DB state and the fresh
    value shows up on the next render.
    """
    prices = refresh_prices_async(symbols)

    stale = stale_symbols(symbols, max_age_hours)[:MAX_PER_REQUEST]
    if not stale:
        return {"queued": 0, "stale": 0, "prices": prices}

    with _lock:
        todo = [s for s in stale if s not in _inflight]
        _inflight.update(todo)

    if not todo:
        return {"queued": 0, "stale": len(stale), "prices": prices}

    _POOL.submit(_refresh_batch, todo)
    return {"queued": len(todo), "stale": len(stale), "prices": prices}


def _refresh_batch(symbols: list[str]) -> None:
    from ingestion.fundamentals_etl import FundamentalsETL
    etl = FundamentalsETL()
    try:
        for sym in symbols:
            try:
                info = etl._yfinance_info(sym, swallow=False)
            except Exception as e:
                logger.debug(f"on-demand refresh failed for {sym}: {e}")
                continue
            if not info or not any(
                info.get(k) for k in ("trailingPE", "returnOnEquity", "priceToBook", "marketCap")
            ):
                continue
            from services.stock_data import fundamentals_from_info
            etl._store_fundamentals(fundamentals_from_info(sym, info))
            etl._store_market_cap(sym, info.get("marketCap"))
            logger.info(f"on-demand refresh: {sym}")
    finally:
        with _lock:
            _inflight.difference_update(symbols)


__all__ = ["refresh_async", "refresh_prices_async", "stale_symbols",
           "stale_prices", "MAX_AGE_HOURS"]
