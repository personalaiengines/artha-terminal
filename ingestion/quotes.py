"""
ARTHA Terminal - Batch quote refresh

Why this exists: ingestion/price_etl.py fetches ONE symbol per HTTP request,
sequentially. Over ~3100 tracked symbols that is ~3100 requests, runs 30-50
minutes, and reliably draws a rate limit partway through — measured on this
deployment, the nightly run reached 1443 of 3117 symbols before dying, leaving
1704 symbols pinned to a stale close. Since every price in the app comes from
`prices_daily`'s newest row per symbol (api/server.py::_universe), those symbols
showed a days-old price everywhere: screener, dashboard, watchlists, and the AI
analyst's factsheet.

yfinance takes a LIST of tickers per download call. Measured here: 100 symbols
in one request, 4.1 seconds, 100/100 populated. So the whole universe is ~31
requests and about two minutes, instead of 3100 requests and an hour.

That changes what's affordable: refreshing prices no longer needs to be a
fragile nightly crawl, so it can also run on demand when a page is viewed and
as a catch-up whenever the data is found stale at boot.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime

from db import get_connection

logger = logging.getLogger("ingestion.quotes")

# 100 tickers/request is the measured sweet spot: one request, ~4s, no throttle.
# Larger batches start returning partial column sets from Yahoo.
CHUNK = 100

# Short window, not full history — this tops up recent closes and heals small
# gaps (a missed cron, a holiday) without refetching years anyone already has.
PERIOD = "5d"

# Between chunks. The per-symbol crawl needed 0.1s between 3100 requests; at 31
# requests a slightly bigger gap is free insurance against a throttle.
PAUSE = 0.4


def _suffixed(symbol: str, exchange: str | None) -> str:
    """Yahoo ticker. BSE symbols 404 on .NS — the exchange decides the suffix."""
    return f"{symbol}.{'BO' if (exchange or '').upper() == 'BSE' else 'NS'}"


def tracked_symbols(stale_only: bool = False, on_or_after: str | None = None) -> list[dict]:
    """Symbols worth refreshing: those we already keep price history for.

    `stale_only` restricts to symbols whose newest candle predates
    `on_or_after`, so a catch-up run doesn't refetch what's already current.
    """
    sql = """
        SELECT m.symbol, m.exchange, p.d AS latest
        FROM symbol_master m
        JOIN (SELECT symbol, MAX(date) d FROM prices_daily GROUP BY symbol) p
          ON p.symbol = m.symbol
    """
    args: tuple = ()
    if stale_only and on_or_after:
        sql += " WHERE p.d < ?"
        args = (on_or_after,)
    with get_connection() as conn:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]


def _rows_for(sym: str, frame) -> list[tuple]:
    """(symbol, date, o, h, l, c, v) rows from one ticker's frame."""
    rows = []
    for ts, r in frame.iterrows():
        close = r.get("Close")
        if close is None or close != close:  # NaN — market shut, or not yet traded
            continue
        try:
            rows.append((
                sym, str(ts)[:10],
                float(r.get("Open") if r.get("Open") == r.get("Open") else close),
                float(r.get("High") if r.get("High") == r.get("High") else close),
                float(r.get("Low") if r.get("Low") == r.get("Low") else close),
                float(close),
                int(r.get("Volume")) if r.get("Volume") == r.get("Volume") else 0,
            ))
        except (TypeError, ValueError):
            continue
    return rows


def refresh(symbols: list[dict] | None = None, period: str = PERIOD) -> dict:
    """Batch-refresh recent candles. Returns {symbols, rows, batches, errors}."""
    import warnings
    warnings.filterwarnings("ignore")
    import yfinance as yf

    targets = symbols if symbols is not None else tracked_symbols()
    if not targets:
        return {"status": "success", "symbols": 0, "rows": 0, "batches": 0, "errors": 0}

    stats = {"symbols": 0, "rows": 0, "batches": 0, "errors": 0}

    for start in range(0, len(targets), CHUNK):
        batch = targets[start:start + CHUNK]
        tickers = {_suffixed(t["symbol"], t.get("exchange")): t["symbol"] for t in batch}
        stats["batches"] += 1
        try:
            df = yf.download(list(tickers), period=period, interval="1d",
                             group_by="ticker", progress=False, threads=True,
                             auto_adjust=False)
        except Exception as e:
            logger.warning(f"batch {stats['batches']} failed: {e}")
            stats["errors"] += 1
            continue

        if df is None or df.empty:
            stats["errors"] += 1
            continue

        rows: list[tuple] = []
        for ticker, sym in tickers.items():
            try:
                # One ticker in the list gives a flat frame, not a MultiIndex.
                frame = df[ticker] if isinstance(df.columns, __import__("pandas").MultiIndex) else df
            except KeyError:
                continue
            got = _rows_for(sym, frame.dropna(how="all"))
            if got:
                rows.extend(got)
                stats["symbols"] += 1

        if rows:
            with get_connection() as conn:
                conn.executemany("""
                    INSERT OR REPLACE INTO prices_daily
                    (symbol, date, open, high, low, close, volume)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, rows)
                conn.commit()
            stats["rows"] += len(rows)

        if start + CHUNK < len(targets):
            time.sleep(PAUSE)

    _refresh_day_change([t["symbol"] for t in targets])
    logger.info(f"quote refresh: {stats}")
    return {"status": "success", **stats}


def _refresh_day_change(symbols: list[str]) -> None:
    """Recompute computed_metrics.return_1d from the two newest closes.

    Without this a refreshed price renders against a day-change computed from
    the previous run's candles — a current price beside a stale % move, which
    reads as more wrong than either alone. The heavier Compute Metrics ETL still
    owns every other derived field; this only keeps the one the price pairs with.
    """
    if not symbols:
        return
    with get_connection() as conn:
        conn.execute("""
            UPDATE computed_metrics AS cm
               SET return_1d = (
                    SELECT ROUND((n.close - p.close) / p.close * 100, 4)
                    FROM (SELECT close, date FROM prices_daily
                           WHERE symbol = cm.symbol ORDER BY date DESC LIMIT 1) n
                    JOIN (SELECT close, date FROM prices_daily
                           WHERE symbol = cm.symbol ORDER BY date DESC LIMIT 1 OFFSET 1) p
                    WHERE p.close > 0
                   ),
                   updated_at = datetime('now')
             WHERE EXISTS (SELECT 1 FROM prices_daily WHERE symbol = cm.symbol)
        """)
        conn.commit()


def latest_trading_date() -> str | None:
    """Newest candle date we hold for the indices — a reliable market calendar.

    Indices are refreshed in three requests and never rate-limited, so their
    newest date is what a fully current equity book should also reach. Avoids
    hardcoding NSE holidays.
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT MAX(date) d FROM prices_daily WHERE symbol IN ('NIFTY','SENSEX','BANKNIFTY')"
        ).fetchone()
    return row["d"] if row and row["d"] else None


def refresh_best(symbols: list[dict] | None = None) -> dict:
    """Refresh via Upstox, falling back to Yahoo.

    Upstox wins on every axis that matters here: authenticated (no rate limit),
    500 keys per request against Yahoo's 100, ~4.4s for the whole universe
    against ~125s, and it carries the CURRENT session while Yahoo publishes its
    daily bar hours late. Yahoo still covers symbols with no ISIN and keeps the
    app working if the Upstox token lapses.
    """
    from services import live_quotes

    if live_quotes.available():
        try:
            res = live_quotes.refresh([t["symbol"] for t in symbols] if symbols else None)
            if res.get("symbols"):
                return {**res, "source": "upstox"}
            logger.warning("upstox returned nothing; falling back to yahoo")
        except Exception as e:
            logger.warning(f"upstox refresh failed, falling back to yahoo: {e}")

    return {**refresh(symbols), "source": "yahoo"}


def catch_up(max_symbols: int = 4000) -> dict:
    """Refresh whatever has fallen behind the latest trading day.

    The nightly cron fires at one exact minute with no misfire grace, so any
    restart or downtime across that minute skipped the run entirely and nothing
    ever went back for it — which is how 1704 symbols came to sit days behind.
    This makes a missed run self-healing instead of permanent.
    """
    # Upstox knows the real session date; the index candles are only a fallback
    # calendar for when it's unavailable.
    target = None
    try:
        from services import live_quotes
        if live_quotes.available():
            import asyncio
            target = asyncio.run(live_quotes.session_date())
    except Exception as e:
        logger.debug(f"upstox session date unavailable: {e}")
    target = target or latest_trading_date()
    if not target:
        return {"status": "skipped", "reason": "no trading date to compare against"}

    stale = tracked_symbols(stale_only=True, on_or_after=target)[:max_symbols]
    if not stale:
        return {"status": "success", "up_to_date": True, "target": target, "symbols": 0}

    logger.info(f"catch-up: {len(stale)} symbols behind {target}")
    return {**refresh_best(stale), "target": target, "stale_found": len(stale)}


__all__ = ["refresh", "refresh_best", "catch_up", "tracked_symbols",
           "latest_trading_date", "CHUNK"]
