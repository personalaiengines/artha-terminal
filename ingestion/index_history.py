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


__all__ = ["run", "INDEX_TICKERS"]
