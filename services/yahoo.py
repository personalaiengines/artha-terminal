"""
ARTHA Terminal - Yahoo Finance Service
Fallback data source using yfinance.
"""

import pandas as pd
from typing import Optional
from datetime import datetime, timedelta


class YahooFinance:
    """
    Yahoo Finance data source via yfinance library.
    Used as fallback when Upstox is unavailable.
    """

    def __init__(self):
        self._cache = {}
        self._cache_ttl = timedelta(hours=1)

    def _format_symbol(self, symbol: str) -> str:
        """
        Format symbol for Yahoo Finance.
        NSE stocks get .NS suffix, BSE get .BO
        """
        symbol = symbol.upper()

        if symbol.endswith(".NS") or symbol.endswith(".BO"):
            return symbol

        # Default to NSE for Indian stocks
        return f"{symbol}.NS"

    def get_quote(self, symbol: str) -> dict | None:
        """
        Get current quote for a symbol.

        Args:
            symbol: Stock symbol (e.g., "RELIANCE", "TCS")

        Returns:
            Dictionary with quote data
        """
        try:
            import yfinance as yf

            formatted = self._format_symbol(symbol)
            ticker = yf.Ticker(formatted)
            info = ticker.info

            return {
                "symbol": symbol,
                "formatted_symbol": formatted,
                "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
                "previous_close": info.get("previousClose"),
                "open": info.get("open"),
                "day_high": info.get("dayHigh"),
                "day_low": info.get("dayLow"),
                "fifty_two_week_high": info.get("fiftyTwoWeekHigh"),
                "fifty_two_week_low": info.get("fiftyTwoWeekLow"),
                "volume": info.get("volume"),
                "avg_volume": info.get("averageVolume"),
                "market_cap": info.get("marketCap"),
                "pe_ratio": info.get("trailingPE"),
                "forward_pe": info.get("forwardPE"),
                "pb_ratio": info.get("priceToBook"),
                "dividend_yield": info.get("dividendYield"),
                "beta": info.get("beta"),
                "eps": info.get("trailingEps"),
                "sector": info.get("sector"),
                "industry": info.get("industry"),
                "business_summary": info.get("longBusinessSummary"),
            }
        except Exception as e:
            return {"error": str(e), "symbol": symbol}

    def get_history(
        self,
        symbol: str,
        period: str = "5y",
        interval: str = "1d"
    ) -> list[dict]:
        """
        Get historical OHLCV data.

        Args:
            symbol: Stock symbol
            period: "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"
            interval: "1d", "1wk", "1mo", "3mo"

        Returns:
            List of OHLCV records
        """
        try:
            import yfinance as yf

            formatted = self._format_symbol(symbol)
            ticker = yf.Ticker(formatted)
            df = ticker.history(period=period, interval=interval)

            if df.empty:
                return []

            data = []
            for idx, row in df.iterrows():
                data.append({
                    "date": idx.strftime("%Y-%m-%d"),
                    "open": float(row["Open"]),
                    "high": float(row["High"]),
                    "low": float(row["Low"]),
                    "close": float(row["Close"]),
                    "volume": int(row["Volume"]),
                    "adj_close": float(row["Adj Close"]) if "Adj Close" in row.index else float(row["Close"]),
                })
            return data
        except Exception as e:
            return []

    def get_fundamentals(self, symbol: str) -> dict:
        """
        Get fundamental financial data.

        Args:
            symbol: Stock symbol

        Returns:
            Dictionary with financial metrics
        """
        try:
            import yfinance as yf

            formatted = self._format_symbol(symbol)
            ticker = yf.Ticker(formatted)

            # Balance sheet
            balance_sheet = ticker.balance_sheet
            cash_flow = ticker.cashflow
            info = ticker.info

            fundamentals = {
                "symbol": symbol,
                "market_cap": info.get("marketCap"),
                "enterprise_value": info.get("enterpriseValue"),
                "trailing_pe": info.get("trailingPE"),
                "forward_pe": info.get("forwardPE"),
                "peg_ratio": info.get("pegRatio"),
                "price_to_book": info.get("priceToBook"),
                "price_to_sales": info.get("priceToSalesTrailing12Months"),
                "enterprise_toRevenue": info.get("enterpriseToRevenue"),
                "enterprise_toEbitda": info.get("enterpriseToEbitda"),
            }

            # Profitability
            if info.get("profitMargins"):
                fundamentals["profit_margin"] = info["profitMargins"]
            if info.get("grossMargins"):
                fundamentals["gross_margin"] = info["grossMargins"]
            if info.get("operatingMargins"):
                fundamentals["operating_margin"] = info["operatingMargins"]
            if info.get("returnOnAssets"):
                fundamentals["roa"] = info["returnOnAssets"]
            if info.get("returnOnEquity"):
                fundamentals["roe"] = info["returnOnEquity"]

            # Financial health
            if balance_sheet is not None and not balance_sheet.empty:
                debts = balance_sheet.get("Total Debt", [])
                cash = balance_sheet.get("Cash and cash equivalents", [])
                if not debts.empty:
                    fundamentals["total_debt"] = debts.iloc[-1]
                if not cash.empty:
                    fundamentals["total_cash"] = cash.iloc[-1]

            return fundamentals
        except Exception as e:
            return {"error": str(e), "symbol": symbol}

    def get_peers(self, symbol: str) -> list[str]:
        """
        Get similar stocks for comparison.

        Returns:
            List ofpeer stock symbols
        """
        try:
            import yfinance as yf

            formatted = self._format_symbol(symbol)
            ticker = yf.Ticker(formatted)

            # Yahoo doesn't provide direct peers, use recommendations
            try:
                rec = ticker.recommendations
                if rec is not None and not rec.empty:
                    return rec["Symbol"].tolist()[:5]
            except Exception:
                pass

            return []
        except Exception:
            return []

    def get_indices(self) -> dict:
        """
        Get major Indian market indices.

        Returns:
            Dictionary with index values
        """
        indices = {
            "nifty50": "^NSI",
            "sensex": "^BSESN",
            "bank_nifty": "^NSEBANK",
            "nifty_midcap": "^CNX MIDDLECAP",
            "nifty_smallcap": "^CNXSmallcap",
        }

        result = {}
        for name, symbol in indices.items():
            quote = self.get_quote(symbol)
            if quote and "error" not in quote:
                result[name] = {
                    "symbol": symbol,
                    "price": quote.get("current_price"),
                    "change": quote.get("previous_close"),
                }

        return result