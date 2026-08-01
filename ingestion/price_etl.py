"""
ARTHA Terminal - Price ETL
Extracts historical OHLCV candle data from Upstox and Yahoo Finance.

Sources:
- Primary: Upstox Historical Candles API (accessible via Analytics Token)
- Fallback: Yahoo Finance (yfinance library)
"""

import sqlite3
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional, List
import logging
import asyncio

from config import config
from db import get_connection

logger = logging.getLogger("ingestion.price_etl")


class PriceETL:
    """ETL pipeline for historical price data."""

    def __init__(self):
        self.upstox = None
        self.yahoo = None
        self._isin_cache: dict | None = None
        self._exchange_cache: dict | None = None
        self._init_clients()

    def _init_clients(self):
        """Initialize data source clients."""
        try:
            from services.upstox import UpstoxClient
            from services.yahoo import YahooFinance

            self.upstox = UpstoxClient() if config.upstox.analytics_token else None
            self.yahoo = YahooFinance()
        except Exception as e:
            logger.warning(f"Client initialization failed: {e}")

    def run(
        self,
        symbols: List[str] | None = None,
        days: int = 365,
        update_stock: bool = False,
    ) -> dict:
        """
        Run price data ETL.

        Args:
            symbols: Specific symbols to update (None = all symbols)
            days: Number of days of history to fetch
            update_stock: Whether to fetch latest prices only

        Returns:
            ETL statistics
        """
        logger.info(f"Starting Price ETL (symbols={symbols or 'all'}, days={days})")

        stats = {
            "symbols_processed": 0,
            "symbols_updated": 0,
            "candles_inserted": 0,
            "upstox_data": 0,
            "yahoo_fallback": 0,
            "errors": 0,
        }

        try:
            # Get symbols to process
            if symbols:
                target_symbols = symbols
            else:
                target_symbols = self._get_tracked_symbols()

            logger.info(f"Processing {len(target_symbols)} symbols")

            # Fetch and store price data
            for symbol in target_symbols:
                result = self._process_symbol(symbol, days)
                stats["symbols_processed"] += 1

                if result["status"] == "success":
                    stats["symbols_updated"] += 1
                    stats["candles_inserted"] += result.get("candles", 0)
                    stats["upstox_data"] += result.get("upstox", 0)
                    stats["yahoo_fallback"] += result.get("yahoo", 0)
                else:
                    stats["errors"] += 1

                # Rate limiting - gentle delay between requests
                import time
                time.sleep(0.1)

            logger.info("Price ETL completed successfully")
            return {"status": "success", **stats}

        except Exception as e:
            logger.error(f"Price ETL failed: {e}")
            stats["errors"] += 1
            return {"status": "error", "error": str(e), **stats}

    def _get_tracked_symbols(self) -> List[str]:
        """Get list of symbols currently in database."""
        try:
            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT DISTINCT symbol FROM symbol_master
                    WHERE symbol IS NOT NULL
                """)
                return [row["symbol"] for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get tracked symbols: {e}")
            return []

    def _process_symbol(
        self,
        symbol: str,
        days: int,
    ) -> dict:
        """
        Fetch and store price data for a single symbol.

        Args:
            symbol: Stock symbol
            days: Number of days of history

        Returns:
            Result with status and statistics
        """
        result = {"status": "error", "symbol": symbol, "candles": 0, "upstox": 0, "yahoo": 0}

        # Calculate date range
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        # Try Upstox first
        if self.upstox:
            candles = self._fetch_upstox(symbol, start_date, end_date)
            if candles:
                inserted = self._store_candles(symbol, candles, "upstox")
                result["status"] = "success"
                result["candles"] = inserted
                result["upstox"] = inserted
                return result

        # Fallback to Yahoo
        if self.yahoo:
            candles = self._fetch_yahoo(symbol, days)
            if candles:
                inserted = self._store_candles(symbol, candles, "yahoo")
                result["status"] = "success"
                result["candles"] = inserted
                result["yahoo"] = inserted
                return result

        return result

    def _fetch_upstox(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> List[dict]:
        """
        Fetch historical candles from Upstox.

        Args:
            symbol: Stock symbol (e.g., RELIANCE)
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)

        Returns:
            List of OHLCV candles
        """
        try:
            import asyncio
            from services.upstox import UpstoxClient

            if not self.upstox:
                return []

            # Convert symbol to Upstox instrument format
            instrument_key = self._to_instrument_key(symbol)
            if not instrument_key:
                logger.debug(f"No ISIN for {symbol}; skipping Upstox, using Yahoo")
                return []

            # Returns raw candle rows, newest first:
            # [[timestamp, open, high, low, close, volume, oi], ...]
            candles = asyncio.run(
                self.upstox.get_candles(
                    instrument_key=instrument_key,
                    interval="day",
                    from_date=start_date,
                    to_date=end_date,
                )
            )

            if candles:
                return self._normalize_upstox_candles(candles)

        except Exception as e:
            logger.debug(f"Upstox fetch failed for {symbol}: {e}")

        return []

    def _normalize_upstox_candles(self, raw_data: List) -> List[dict]:
        """
        Normalize Upstox candle format.

        Upstox format: [timestamp, open, high, low, close, volume]
        """
        candles = []
        for item in raw_data:
            if len(item) >= 6:
                try:
                    timestamp = item[0]
                    if isinstance(timestamp, (int, float)):
                        # Unix timestamp
                        dt = datetime.fromtimestamp(timestamp / 1000)
                        date_str = dt.strftime("%Y-%m-%d")
                    else:
                        # Already a string date
                        date_str = str(timestamp)[:10]

                    candles.append({
                        "date": date_str,
                        "open": float(item[1]) if item[1] else None,
                        "high": float(item[2]) if item[2] else None,
                        "low": float(item[3]) if item[3] else None,
                        "close": float(item[4]) if item[4] else None,
                        "volume": int(item[5]) if item[5] else None,
                    })
                except Exception as e:
                    logger.warning(f"Failed to parse candle: {e}")

        return sorted(candles, key=lambda x: x["date"])

    def _fetch_yahoo(
        self,
        symbol: str,
        days: int,
    ) -> List[dict]:
        """
        Fetch historical data from Yahoo Finance.

        Args:
            symbol: Stock symbol
            days: Number of days of history

        Returns:
            List of OHLCV candles
        """
        try:
            if not self.yahoo:
                return []

            # Calculate period based on days
            if days <= 30:
                period = "1mo"
            elif days <= 90:
                period = "3mo"
            elif days <= 180:
                period = "6mo"
            elif days <= 365:
                period = "1y"
            elif days <= 730:
                period = "2y"
            else:
                period = "5y"

            # BSE-only symbols have no .NS listing — suffix must match the
            # actual exchange or yfinance 404s and the ETL silently gets nothing.
            exch = self._exchange_map().get(symbol.upper())
            suffixed = f"{symbol}.BO" if exch == "BSE" else f"{symbol}.NS"
            history = self.yahoo.get_history(suffixed, period=period, interval="1d")

            if history:
                # Filter to requested date range
                end_date = datetime.now().date()
                start_date = end_date - timedelta(days=days)

                filtered = [
                    h for h in history
                    if start_date <= datetime.strptime(h["date"], "%Y-%m-%d").date() <= end_date
                ]

                # Deduplicate by date (keep latest)
                seen = set()
                unique = []
                for h in reversed(filtered):  # Newest first
                    if h["date"] not in seen:
                        seen.add(h["date"])
                        unique.insert(0, h)  # Add to beginning

                return unique

        except Exception as e:
            logger.debug(f"Yahoo fetch failed for {symbol}: {e}")

        return []

    def _to_instrument_key(self, symbol: str) -> str:
        """
        Convert an NSE symbol to an Upstox v2 instrument key.

        Upstox keys equities by ISIN, not by trading symbol — a key built from
        the symbol (NSE_EQ|RELIANCE) is rejected with UDAPI100011 "Invalid
        Instrument key". We resolve the ISIN from symbol_master.

        Example: RELIANCE -> NSE_EQ|INE002A01018

        Returns "" when the ISIN is unknown, so the caller can fall back to Yahoo.
        """
        isin = self._isin_map().get(symbol.upper())
        if not isin:
            return ""

        exchange = "BSE_EQ" if self._exchange_map().get(symbol.upper()) == "BSE" else "NSE_EQ"
        return f"{exchange}|{isin}"

    def _isin_map(self) -> dict:
        """symbol -> ISIN, loaded once per ETL run."""
        if self._isin_cache is None:
            self._load_symbol_meta()
        return self._isin_cache

    def _exchange_map(self) -> dict:
        """symbol -> exchange, loaded once per ETL run."""
        if self._exchange_cache is None:
            self._load_symbol_meta()
        return self._exchange_cache

    def _load_symbol_meta(self) -> None:
        """Load symbol -> (ISIN, exchange) from symbol_master."""
        isins: dict = {}
        exchanges: dict = {}
        try:
            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT symbol, isin, exchange FROM symbol_master WHERE isin IS NOT NULL"
                )
                for row in cursor.fetchall():
                    isins[row["symbol"].upper()] = row["isin"]
                    exchanges[row["symbol"].upper()] = row["exchange"]
        except Exception as e:
            logger.warning(f"Could not load ISIN map from symbol_master: {e}")

        self._isin_cache = isins
        self._exchange_cache = exchanges

    def _store_candles(
        self,
        symbol: str,
        candles: List[dict],
        source: str,
    ) -> int:
        """
        Store candles in database.

        Args:
            symbol: Stock symbol
            candles: List of OHLCV records
            source: Data source ('upstox' or 'yahoo')

        Returns:
            Number of candles inserted/updated
        """
        inserted = 0

        with get_connection() as conn:
            cursor = conn.cursor()

            for candle in candles:
                try:
                    # Check if already exists
                    cursor.execute(
                        """
                        SELECT 1 FROM prices_daily
                        WHERE symbol = ? AND date = ?
                        """,
                        (symbol, candle["date"]),
                    )
                    exists = cursor.fetchone()

                    if exists:
                        # Update existing record
                        cursor.execute(
                            """
                            UPDATE prices_daily
                            SET open = ?, high = ?, low = ?, close = ?, volume = ?,
                                source = ?, updated_at = datetime('now')
                            WHERE symbol = ? AND date = ?
                            """,
                            (
                                candle.get("open"),
                                candle.get("high"),
                                candle.get("low"),
                                candle.get("close"),
                                candle.get("volume"),
                                source,
                                symbol,
                                candle["date"],
                            ),
                        )
                    else:
                        # Insert new record
                        cursor.execute(
                            """
                            INSERT INTO prices_daily
                            (symbol, date, open, high, low, close, volume, source, created_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                            """,
                            (
                                symbol,
                                candle["date"],
                                candle.get("open"),
                                candle.get("high"),
                                candle.get("low"),
                                candle.get("close"),
                                candle.get("volume"),
                                source,
                            ),
                        )
                    inserted += 1
                except Exception as e:
                    logger.warning(f"Failed to store candle for {symbol} on {candle.get('date')}: {e}")

            conn.commit()

        return inserted

    def get_latest_prices(self, symbols: List[str] | None = None) -> dict:
        """
        Get latest prices for symbols.

        Args:
            symbols: List of symbols (None = all tracked)

        Returns:
            Dictionary mapping symbol to latest price data
        """
        price_data = {}

        # If specific symbols requested
        if symbols:
            for symbol in symbols:
                latest = self._get_symbol_latest(symbol)
                if latest:
                    price_data[symbol] = latest
        else:
            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT symbol, date, open, high, low, close, volume
                    FROM prices_daily p1
                    WHERE date = (
                        SELECT MAX(date) FROM prices_daily p2 WHERE p2.symbol = p1.symbol
                    )
                """)

                for row in cursor.fetchall():
                    price_data[row["symbol"]] = {
                        "date": row["date"],
                        "open": row["open"],
                        "high": row["high"],
                        "low": row["low"],
                        "close": row["close"],
                        "volume": row["volume"],
                    }

        return price_data

    def _get_symbol_latest(self, symbol: str) -> dict | None:
        """Get latest price for a single symbol."""
        try:
            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT date, open, high, low, close, volume, source
                    FROM prices_daily
                    WHERE symbol = ?
                    ORDER BY date DESC
                    LIMIT 1
                """, (symbol,))
                row = cursor.fetchone()

                if row:
                    return {
                        "date": row["date"],
                        "open": row["open"],
                        "high": row["high"],
                        "low": row["low"],
                        "close": row["close"],
                        "volume": row["volume"],
                        "source": row["source"],
                    }
        except Exception as e:
            logger.error(f"Failed to get latest price for {symbol}: {e}")

        return None

    def backfill(
        self,
        symbols: List[str],
        start_date: str,
        end_date: str | None = None,
    ) -> dict:
        """
        Backfill historical data for a date range.

        Args:
            symbols: Symbols to backfill
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD), defaults to today

        Returns:
            Backfill statistics
        """
        if end_date is None:
            end_date = datetime.now().strftime("%Y-%m-%d")

        stats = {"symbols": 0, "candles": 0, "errors": 0}

        for symbol in symbols:
            result = self._process_symbol(symbol, 3650)  # ~10 years
            stats["symbols"] += 1
            stats["candles"] += result.get("candles", 0)
            if result["status"] == "error":
                stats["errors"] += 1

        return stats