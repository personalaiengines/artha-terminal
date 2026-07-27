"""
ARTHA Terminal - Computed Metrics ETL
Calculates derived metrics: DMAs, returns, ATH/ATL, percentiles, segment classification.
"""

import sqlite3
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from typing import List, Dict
import logging

from config import config
from db import get_connection

logger = logging.getLogger("ingestion.compute_metrics")


class MetricsCalculator:
    """Computes derived metrics from raw price and fundamental data."""

    def __init__(self):
        pass

    def run(self) -> dict:
        """
        Run all metrics computations.

        Returns:
            Statistics about computed metrics
        """
        logger.info("Starting Computed Metrics ETL...")

        stats = {
            "symbols_processed": 0,
            "symbols_updated": 0,
            "errors": 0,
        }

        try:
            # Get all symbols with price data
            symbols = self._get_symbols_with_prices()
            stats["symbols_processed"] = len(symbols)

            for symbol in symbols:
                try:
                    self._compute_symbol_metrics(symbol)
                    stats["symbols_updated"] += 1
                except Exception as e:
                    logger.error(f"Failed to compute metrics for {symbol}: {e}")
                    stats["errors"] += 1

            logger.info("Computed Metrics ETL completed")
            return {"status": "success", **stats}

        except Exception as e:
            logger.error(f"Metrics computation failed: {e}")
            return {"status": "error", "error": str(e), **stats}

    def _get_symbols_with_prices(self) -> List[str]:
        """Get symbols that have price data."""
        try:
            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT DISTINCT symbol FROM prices_daily
                    WHERE symbol IS NOT NULL
                """)
                return [row["symbol"] for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get symbols: {e}")
            return []

    def _compute_symbol_metrics(self, symbol: str):
        """
        Compute all metrics for a single symbol.

        Args:
            symbol: Stock symbol
        """
        # Fetch price data
        prices_df = self._fetch_price_data(symbol)

        if prices_df.empty:
            logger.warning(f"No price data for {symbol}")
            return

        # Compute technical indicators
        dma_50 = self._compute_dma(prices_df, 50)
        dma_200 = self._compute_dma(prices_df, 200)
        rsi_14 = self._compute_rsi(prices_df, 14)

        # Compute ATH/ATL
        ath, ath_date = self._compute_ath(prices_df)
        atl, atl_date = self._compute_atl(prices_df)

        # Compute returns
        returns = self._compute_returns(prices_df)

        # Compute percentiles vs own 5Y history
        price_percentile, pe_percentile, pb_percentile = self._compute_percentiles(symbol, prices_df)

        # Get market cap classification
        cap_segment = self._classify_market_cap(symbol)

        # Fetch latest price
        latest_price = self._get_latest_price(prices_df)

        # Fetch fundamental data for ratios
        fundamentals = self._fetch_fundamentals(symbol)

        # Store computed metrics
        self._store_metrics(
            symbol=symbol,
            dma_50=dma_50,
            dma_200=dma_200,
            rsi_14=rsi_14,
            ath=ath,
            ath_date=ath_date,
            atl=atl,
            atl_date=atl_date,
            returns=returns,
            price_percentile=price_percentile,
            pe_percentile=pe_percentile,
            pb_percentile=pb_percentile,
            cap_segment=cap_segment,
            latest_price=latest_price,
            fundamentals=fundamentals,
        )

    def _fetch_price_data(self, symbol: str) -> pd.DataFrame:
        """Fetch price data for a symbol with NaN rows stripped."""
        try:
            with get_connection() as conn:
                query = """
                    SELECT date, open, high, low, close, volume
                    FROM prices_daily
                    WHERE symbol = ?
                    ORDER BY date
                    """
                df = pd.read_sql_query(query, conn, params=(symbol,))
                if not df.empty:
                    df["date"] = pd.to_datetime(df["date"])
                    # Strip rows where critical price fields are NaN
                    # (handles incomplete intraday candles where close isn't posted yet)
                    before = len(df)
                    df = df.dropna(subset=["close", "high", "low"])
                    if len(df) < before:
                        logger.debug(f"Stripped {before - len(df)} NaN row(s) for {symbol}")
                return df
        except Exception as e:
            logger.error(f"Failed to fetch prices for {symbol}: {e}")
            return pd.DataFrame()

    def _compute_dma(self, prices_df: pd.DataFrame, period: int) -> float | None:
        """
        Compute Moving Average.

        Args:
            prices_df: DataFrame with 'close' column
            period: Number of periods

        Returns:
            Current DMA value or None
        """
        if len(prices_df) < period:
            return None

        prices_df = prices_df.copy()
        prices_df["dma"] = prices_df["close"].rolling(window=period).mean()

        return float(prices_df["dma"].iloc[-1]) if not pd.isna(prices_df["dma"].iloc[-1]) else None

    def _compute_rsi(self, prices_df: pd.DataFrame, period: int = 14) -> float | None:
        """
        Compute Relative Strength Index.

        Args:
            prices_df: DataFrame with 'close' column
            period: RSI period (default 14)

        Returns:
            Current RSI value or None
        """
        if len(prices_df) < period + 1:
            return None

        prices_df = prices_df.copy()
        prices_df["delta"] = prices_df["close"].diff()

        gain = (prices_df["delta"].where(prices_df["delta"] > 0, 0)).rolling(window=period).mean()
        loss = (-prices_df["delta"].where(prices_df["delta"] < 0, 0)).rolling(window=period).mean()

        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))

        return float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else None

    def _compute_ath(self, prices_df: pd.DataFrame) -> tuple[float | None, str | None]:
        """
        Compute All-Time High and date it occurred.

        Returns:
            (ATH value, date of ATH)
        """
        if prices_df.empty or "high" not in prices_df.columns:
            return None, None

        max_idx = prices_df["high"].idxmax()
        ath = float(prices_df.loc[max_idx, "high"])
        ath_date = str(prices_df.loc[max_idx, "date"])

        return ath, ath_date

    def _compute_atl(self, prices_df: pd.DataFrame) -> tuple[float | None, str | None]:
        """
        Compute All-Time Low and date it occurred.

        Returns:
            ATL value, date of ATL
        """
        if prices_df.empty or "low" not in prices_df.columns:
            return None, None

        min_idx = prices_df["low"].idxmin()
        atl = float(prices_df.loc[min_idx, "low"])
        atl_date = str(prices_df.loc[min_idx, "date"])

        return atl, atl_date

    def _compute_returns(self, prices_df: pd.DataFrame) -> Dict[str, float | None]:
        """
        Compute returns for multiple timeframes.

        Returns:
            Dictionary with return percentages
        """
        returns = {
            "return_1d": None,
            "return_1w": None,
            "return_1m": None,
            "return_3m": None,
            "return_6m": None,
            "return_1y": None,
            "return_3y": None,
            "return_5y": None,
        }

        if prices_df.empty or len(prices_df) < 2:
            return returns

        current_price = prices_df["close"].iloc[-1]

        today = pd.Timestamp(prices_df["date"].iloc[-1])

        # Define lookback periods
        lookbacks = {
            "return_1d": 1,
            "return_1w": 7,
            "return_1m": 30,
            "return_3m": 90,
            "return_6m": 180,
            "return_1y": 365,
            "return_3y": 365 * 3,
            "return_5y": 365 * 5,
        }

        for key, days in lookbacks.items():
            cutoff_date = today - pd.Timedelta(days=days)

            # Find the closest price before or on cutoff
            subset = prices_df[prices_df["date"] <= cutoff_date]

            if not subset.empty:
                old_price = subset["close"].iloc[-1]
                if old_price and old_price > 0:
                    returns[key] = ((current_price / old_price) - 1) * 100

        return returns

    def _compute_percentiles(
        self,
        symbol: str,
        prices_df: pd.DataFrame,
    ) -> tuple[float | None, float | None, float | None]:
        """
        Compute price, P/E, P/B percentiles vs own 5Y history.

        Returns:
            (price_percentile, pe_percentile, pb_percentile)
        """
        # Price percentile
        if len(prices_df) < 252:  # ~1 year of trading days
            return None, None, None

        current_price = prices_df["close"].iloc[-1]
        historical_prices = prices_df["close"].dropna()

        price_percentile = (historical_prices < current_price).sum() / len(historical_prices) * 100

        # P/E and P/B percentiles require historical fundamental data
        # For now, return None (would need daily fundamental snapshots)
        return float(price_percentile), None, None

    def _classify_market_cap(self, symbol: str) -> str:
        """
        Classify stock by market cap segment.

        Large Cap: Rank 1-100
        Mid Cap: Rank 101-250
        Small Cap: Rank 251+

        Returns:
            Segment classification
        """
        try:
            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT mcap_rank FROM symbol_master
                    WHERE symbol = ?
                """, (symbol,))
                row = cursor.fetchone()

                if row and row["mcap_rank"]:
                    rank = int(row["mcap_rank"])
                    if rank <= 100:
                        return "Large"
                    elif rank <= 250:
                        return "Mid"
                    else:
                        return "Small"

                return "Other"
        except Exception as e:
            logger.debug(f"Failed to classify market cap for {symbol}: {e}")
            return "Other"

    def _get_latest_price(self, prices_df: pd.DataFrame) -> float | None:
        """Get the latest valid closing price."""
        if prices_df.empty:
            return None

        valid = prices_df["close"].dropna()
        if valid.empty:
            return None

        return float(valid.iloc[-1])

    def _fetch_fundamentals(self, symbol: str) -> dict:
        """Fetch latest fundamentals for a symbol."""
        try:
            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT pe_ratio, pb_ratio FROM fundamentals
                    WHERE symbol = ?
                """, (symbol,))
                row = cursor.fetchone()

                if row:
                    return {
                        "pe_ratio": row["pe_ratio"],
                        "pb_ratio": row["pb_ratio"],
                    }
        except Exception as e:
            logger.debug(f"Failed to fetch fundamentals for {symbol}: {e}")

        return {}

    def _store_metrics(
        self,
        symbol: str,
        dma_50: float | None,
        dma_200: float | None,
        rsi_14: float | None,
        ath: float | None,
        ath_date: str | None,
        atl: float | None,
        atl_date: str | None,
        returns: Dict[str, float | None],
        price_percentile: float | None,
        pe_percentile: float | None,
        pb_percentile: float | None,
        cap_segment: str,
        latest_price: float | None,
        fundamentals: dict,
    ):
        """Store computed metrics in database."""
        try:
            # Calculate distance from ATH/ATL
            distance_from_ath = None
            distance_from_atl = None

            if latest_price and ath:
                distance_from_ath = ((latest_price / ath) - 1) * 100
            if latest_price and atl:
                distance_from_atl = ((latest_price / atl) - 1) * 100

            with get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute(
                    """
                    INSERT OR REPLACE INTO computed_metrics
                    (symbol, dma_50, dma_200, rsi_14,
                     ath, atl, ath_date, atl_date,
                     distance_from_ath, distance_from_atl,
                     return_1d, return_1w, return_1m, return_3m,
                     return_6m, return_1y, return_3y, return_5y,
                     price_percentile_5y, pe_percentile_5y, pb_percentile_5y,
                     sector, industry, cap_segment,
                     last_calculated, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                    """,
                    (
                        symbol,
                        dma_50,
                        dma_200,
                        rsi_14,
                        ath,
                        atl,
                        ath_date,
                        atl_date,
                        distance_from_ath,
                        distance_from_atl,
                        returns.get("return_1d"),
                        returns.get("return_1w"),
                        returns.get("return_1m"),
                        returns.get("return_3m"),
                        returns.get("return_6m"),
                        returns.get("return_1y"),
                        returns.get("return_3y"),
                        returns.get("return_5y"),
                        price_percentile,
                        pe_percentile,
                        pb_percentile,
                        fundamentals.get("sector"),
                        fundamentals.get("industry"),
                        cap_segment,
                    ),
                )

                conn.commit()

        except Exception as e:
            logger.error(f"Failed to store metrics for {symbol}: {e}")

    def update_atl_ath_for_all(self):
        """
        Bulk update ATH/ATL for all symbols.
        Use after significant market movements.
        """
        symbols = self._get_symbols_with_prices()
        count = 0

        for symbol in symbols:
            prices_df = self._fetch_price_data(symbol)
            if not prices_df.empty:
                ath, ath_date = self._compute_ath(prices_df)
                atl, atl_date = self._compute_atl(prices_df)

                # Update in database
                try:
                    with get_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            """
                            UPDATE computed_metrics
                            SET ath = ?, ath_date = ?, atl = ?, atl_date = ?,
                                updated_at = datetime('now')
                            WHERE symbol = ?
                            """,
                            (ath, ath_date, atl, atl_date, symbol),
                        )
                        count += 1
                except Exception as e:
                    logger.error(f"Failed to update ATH/ATL for {symbol}: {e}")

        return {"updated": count}