"""
ARTHA Terminal - Index OHLC history

prices_daily held equities only, so the F&O page had no real index candles and
drew synthetic ones (lib/data.ts::candles() seeded on the live spot). This
ingests real daily OHLC for the traded indices into the same table, under the
symbol names the F&O page already uses, so /api/history can serve them like any
other symbol.

Only three requests per run — safe to run alongside the heavier ETLs.
"""

from __future__ import annotations

import logging

from db import get_connection

logger = logging.getLogger("ingestion.index_history")

# F&O page symbol -> yfinance ticker
INDEX_TICKERS = {
    "NIFTY": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "SENSEX": "^BSESN",
    # India VIX. A bare VIX number says nothing without its own distribution
    # behind it, and nothing anywhere stored one; it rides the same loop, the
    # same table and the same /api/history shape. Volume is always 0.
    "INDIAVIX": "^INDIAVIX",
}


def run(period: str = "1y") -> dict:
    import warnings
    warnings.filterwarnings("ignore")
    import yfinance as yf

    stats = {"indices": 0, "rows": 0, "errors": 0}

    for symbol, ticker in INDEX_TICKERS.items():
        try:
            df = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=False)
        except Exception as e:
            logger.warning(f"{symbol} ({ticker}) fetch failed: {e}")
            stats["errors"] += 1
            continue

        if df is None or df.empty:
            logger.warning(f"{symbol} ({ticker}) returned no data")
            stats["errors"] += 1
            continue

        df = df.reset_index()
        date_col = "Date" if "Date" in df.columns else df.columns[0]
        rows = []
        for _, r in df.iterrows():
            try:
                close = float(r["Close"])
            except (TypeError, ValueError):
                continue  # partially-formed candle for today
            if close != close:  # NaN
                continue
            rows.append((
                symbol,
                str(r[date_col])[:10],
                float(r["Open"]), float(r["High"]), float(r["Low"]), close,
                int(r["Volume"]) if r.get("Volume") == r.get("Volume") else 0,
            ))

        if not rows:
            continue

        with get_connection() as conn:
            conn.executemany("""
                INSERT OR REPLACE INTO prices_daily
                (symbol, date, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, rows)
            conn.commit()

        stats["indices"] += 1
        stats["rows"] += len(rows)
        logger.info(f"{symbol}: {len(rows)} candles")

    return {"status": "success", **stats}


def catch_up(target: str | None = None, period: str = "1mo") -> dict:
    """Re-run the index ingest if it missed its cron window.

    APScheduler never replays a fire the process was down for, so a restart
    spanning 20:45 IST skipped that evening permanently — two consecutive
    rebuilds left the index candles two sessions behind the equities while the
    job itself reported nothing wrong. Same self-healing idea as
    ingestion.quotes.catch_up, and `run` is INSERT OR REPLACE, so re-running is
    free.

    `target` is the session we should already hold; callers that just computed
    it (api.server passes it straight from the quotes catch-up) save a second
    Upstox round-trip. NOT ingestion.quotes.latest_trading_date() — that reads
    MAX(date) of these very index symbols, so comparing against it would always
    say "up to date". Falling back on the newest date in prices_daily as a
    whole catches exactly the observed case: equities current, indices behind.
    """
    if not target:
        try:
            from services import live_quotes
            if live_quotes.available():
                import asyncio
                target = asyncio.run(live_quotes.session_date())
        except Exception as e:
            logger.debug(f"upstox session date unavailable: {e}")

    with get_connection() as conn:
        have = conn.execute(
            "SELECT MAX(date) d FROM prices_daily WHERE symbol = 'NIFTY'"
        ).fetchone()["d"]
        if not target:
            target = conn.execute("SELECT MAX(date) d FROM prices_daily").fetchone()["d"]

    if not target:
        return {"status": "skipped", "reason": "no trading date to compare against"}
    if have and have >= target:
        return {"status": "success", "up_to_date": True, "target": target, "have": have}

    logger.info(f"index candles at {have}, behind {target} - backfilling")
    return {**run(period=period), "target": target, "was": have}


__all__ = ["run", "catch_up", "INDEX_TICKERS"]
