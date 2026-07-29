"""
ARTHA Terminal - Fundamentals ETL

Source: yfinance .info, via the same fundamentals_from_info() mapping the live
per-symbol page uses, so batch and live can't drift apart.

The original screener.in scraper is retained below (_parse_screener_page and
friends) but is no longer on the ingest path: its ratio-table parse was wrong,
producing P/E values like -40854 and 74931 with every other field null across
all 70 rows it ever managed to write.
"""

import requests
import sqlite3
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime
from typing import Optional, List
import logging
import time

from config import config
from db import get_connection

logger = logging.getLogger("ingestion.fundamentals_etl")


class FundamentalsETL:
    """ETL pipeline for fundamental financial data."""

    def __init__(self):
        self.base_url = "https://www.screener.in"
        self.session = requests.Session()
        # 0.6s is the cadence that completed a full 5173-symbol yfinance pass
        # without tripping Yahoo's IP block; 2.0s made a full run take ~3h.
        self.request_delay = 0.6

    def run(
        self,
        symbols: List[str] | None = None,
        max_per_run: int | None = None,
        only_missing: bool = False,
    ) -> dict:
        """
        Run fundamentals ETL against yfinance.

        Previously this scraped screener.in and was doubly broken: the parser
        mis-read the ratio tables (it produced P/E values like -40854 and
        74931 with every other field null), and it was capped at 50 symbols
        per weekly run over a hardcoded LIMIT 100 symbol list — so it could
        never cover the universe even if the parse had been correct.

        yfinance is the same source already trusted for the live per-symbol
        page, and the mapping is shared with it via fundamentals_from_info().

        Args:
            symbols: Specific symbols to update (None = all in symbol_master)
            max_per_run: Optional cap; None means no cap
            only_missing: Skip symbols that already have a fundamentals row

        Returns:
            ETL statistics
        """
        logger.info("Starting Fundamentals ETL (yfinance)...")

        stats = {"symbols_processed": 0, "symbols_updated": 0, "errors": 0, "no_data": 0}

        try:
            target_symbols = symbols or self._get_tracked_symbols(only_missing=only_missing)
            if max_per_run:
                target_symbols = target_symbols[:max_per_run]

            logger.info(f"Processing {len(target_symbols)} symbols")

            error_streak = 0
            for i, symbol in enumerate(target_symbols, 1):
                stats["symbols_processed"] += 1
                try:
                    info = self._yfinance_info(symbol, swallow=False)
                    error_streak = 0
                except Exception:
                    stats["errors"] += 1
                    error_streak += 1
                    # Yahoo blocks this container's IP under sustained load.
                    # A long run of genuine HTTP errors means we're blocked;
                    # keep going through mere "no data" symbols, which are
                    # normal for shells and delisted lines.
                    if error_streak >= 25:
                        logger.warning("Aborting: 25 consecutive HTTP errors — likely rate-limited")
                        break
                    continue

                # yfinance answers 200 with an essentially empty payload for
                # shells/delisted lines; treat that as "no data", not an error.
                if not any(info.get(k) for k in ("trailingPE", "returnOnEquity", "priceToBook", "marketCap")):
                    stats["no_data"] += 1
                    continue

                from services.stock_data import fundamentals_from_info
                self._store_fundamentals(fundamentals_from_info(symbol, info))
                self._store_market_cap(symbol, info.get("marketCap"))
                stats["symbols_updated"] += 1

                if i % 100 == 0:
                    logger.info(f"  {i}/{len(target_symbols)} ({stats['symbols_updated']} updated)")

                time.sleep(self.request_delay)

            logger.info(f"Fundamentals ETL completed: {stats}")
            return {"status": "success", **stats}

        except Exception as e:
            logger.error(f"Fundamentals ETL failed: {e}")
            return {"status": "error", "error": str(e), **stats}

    def _get_tracked_symbols(self, only_missing: bool = False) -> List[str]:
        """Symbols to refresh. The old `LIMIT 100` here was the hard ceiling
        that kept fundamentals at ~1% coverage of a 5000+ symbol universe."""
        try:
            sql = "SELECT symbol FROM symbol_master WHERE symbol IS NOT NULL"
            if only_missing:
                sql += " AND symbol NOT IN (SELECT symbol FROM fundamentals)"
            sql += " ORDER BY symbol"
            with get_connection() as conn:
                return [row["symbol"] for row in conn.execute(sql).fetchall()]
        except Exception as e:
            logger.error(f"Failed to get tracked symbols: {e}")
            return []

    def _store_market_cap(self, symbol: str, market_cap: float | None) -> None:
        """symbol_master.market_cap_cr was NULL for 100% of the universe —
        nothing ever wrote it. yfinance gives it in rupees; the column is crore."""
        if not market_cap:
            return
        try:
            with get_connection() as conn:
                conn.execute(
                    "UPDATE symbol_master SET market_cap_cr=?, updated_at=datetime('now') WHERE symbol=?",
                    (round(float(market_cap) / 1e7, 2), symbol),
                )
                conn.commit()
        except Exception as e:
            logger.debug(f"market cap write failed for {symbol}: {e}")

    def _process_symbol(self, symbol: str) -> dict:
        """
        Fetch and store fundamentals for a single symbol.

        Args:
            symbol: Stock symbol

        Returns:
            Result with status
        """
        result = {"status": "error", "symbol": symbol}

        try:
            # Screener.in URL format: https://www.screener.in/company/SYMBOL/
            url = f"{self.base_url}/company/{symbol}/"

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html,application/xhtml+xml, application/xml;q=0.9,*/*;q=0.8",
            }

            response = self.session.get(url, headers=headers, timeout=30)

            if response.status_code == 429:
                logger.warning(f"Rate limited for {symbol}")
                return {"status": "rate_limited", "symbol": symbol}

            if response.status_code != 200:
                logger.warning(f"Failed to fetch {symbol}: {response.status_code}")
                return result

            # Parse and extract data
            data = self._parse_screener_page(response.text, symbol)

            if data:
                self._store_fundamentals(data)
                result["status"] = "success"
                result["data"] = data
            else:
                logger.warning(f"No data found for {symbol}")

        except Exception as e:
            logger.error(f"Failed to process {symbol}: {e}")

        return result

    def _parse_screener_page(self, html: str, symbol: str) -> dict | None:
        """
        Parse Screener.in HTML and extract financial data.

        Note: This is a simplified extractor. Production would need:
        - More robust HTML parsing
        - Handling of Screener's dynamic elements
        - Extraction from multiple pages (cash flow, ratios, etc.)
        """
        try:
            soup = BeautifulSoup(html, "lxml")

            # Company info extraction
            company_info = self._extract_company_info(soup, symbol)

            # Key ratios from the main ratios table
            ratios = self._extract_ratios(soup)

            # Balance sheet data
            balance_sheet = self._extract_balance_sheet(soup)

            # Cash flow data
            cash_flow = self._extract_cash_flow(soup)

            # Profit & Loss data
            pl_data = self._extract_profit_loss(soup)

            # Combine all data
            return {
                "symbol": symbol,
                "date_updated": datetime.now().strftime("%Y-%m-%d"),
                **company_info,
                **ratios,
                **balance_sheet,
                **cash_flow,
                **pl_data,
            }

        except Exception as e:
            logger.error(f"Failed to parse page for {symbol}: {e}")
            return None

    def _yfinance_info(self, symbol: str, swallow: bool = True) -> dict | None:
        """Single exchange-aware yfinance .info fetch, shared by the sector
        and company-name backfills so both don't double the network calls
        for the same symbol.

        BSE-only symbols have no .NS listing — always 404 there — so the
        suffix must match the symbol's actual exchange (same fix as
        services/stock_data.py::get_live_stock_data).

        swallow=False lets a real connectivity/HTTP failure propagate instead
        of collapsing into "call succeeded, this obscure micro-cap just has
        no data in yfinance at all" — callers that need to tell an actual
        block apart from genuine sparse coverage (scripts/backfill_sector.py's
        circuit breaker) need that distinction."""
        try:
            import yfinance as yf
            from db import get_connection

            exchange = "NSE"
            try:
                with get_connection() as conn:
                    row = conn.execute(
                        "SELECT exchange FROM symbol_master WHERE symbol=?", (symbol,)
                    ).fetchone()
                    if row and row["exchange"]:
                        exchange = row["exchange"]
            except Exception:
                pass

            suffix = ".NS" if exchange == "NSE" else ".BO"
            return yf.Ticker(f"{symbol}{suffix}").info
        except Exception as e:
            logger.debug(f"yfinance info fetch failed for {symbol}: {e}")
            if not swallow:
                raise
            return None

    def _yfinance_sector_industry(self, symbol: str, swallow: bool = True) -> tuple[str | None, str | None]:
        """Screener's breadcrumb scrape is fragile (markup changes, missing
        breadcrumb) and was returning None for every symbol in production —
        yfinance's .info is the same sector source already relied on
        elsewhere in this app (services/stock_data.py) and is reliable."""
        info = self._yfinance_info(symbol, swallow=swallow) or {}
        return info.get("sector"), info.get("industry")

    def _extract_company_info(self, soup: BeautifulSoup, symbol: str) -> dict:
        """Extract basic company information."""
        name_elem = soup.find("title")
        company_name = name_elem.get_text().split("-")[0].strip() if name_elem else symbol

        # Get sector/industry from page
        # Screener shows structure like: Home > Equity > SECTOR > COMPANY
        sector = None
        industry = None
        try:
            breadcrumb = soup.find("ul", class_="breadcrumb")
            if breadcrumb:
                links = breadcrumb.find_all("a")
                if len(links) >= 3:
                    sector = links[-2].get_text().strip()
                    industry = links[-1].get_text().strip()
        except Exception as e:
            logger.debug(f"Screener breadcrumb parse failed for {symbol}: {e}")

        if not sector:
            sector, industry = self._yfinance_sector_industry(symbol)

        return {
            "company_name": company_name,
            "sector": sector,
            "industry": industry,
        }

    def _extract_ratios(self, soup: BeautifulSoup) -> dict:
        """Extract key financial ratios."""
        ratios = {}

        try:
            # Find ratios table
            tables = soup.find_all("table")

            for table in tables:
                rows = table.find_all("tr")
                for row in rows:
                    cells = row.find_all("td")
                    if len(cells) >= 2:
                        label = cells[0].get_text().strip().lower()
                        value_text = cells[-1].get_text().strip()

                        # Parse value
                        value = self._parse_financial_value(value_text)

                        # Map to our schema
                        ratio_mapping = {
                            "pe": "pe_ratio",
                            "price to x": "pb_ratio",  # PB ratio
                            "book value": "book_value",
                            "dividend yield": "dividend_yield",
                            "market cap": "market_cap_cr",
                            "sales": None,  # Will handle separately
                            "interest": None,
                        }

                        for key, target in ratio_mapping.items():
                            if key in label and target:
                                ratios[target] = value

        except Exception as e:
            logger.debug(f"Failed to extract ratios: {e}")

        return ratios

    def _extract_balance_sheet(self, soup: BeautifulSoup) -> dict:
        """Extract balance sheet items."""
        data = {}

        try:
            tables = soup.find_all("table")

            for table in tables:
                # Look for balance sheet related rows
                rows = table.find_all("tr")
                for row in rows:
                    cells = row.find_all("td")
                    if len(cells) >= 2:
                        label = cells[0].get_text().strip().lower()
                        value_text = cells[-1].get_text().strip()
                        value = self._parse_financial_value(value_text)

                        # Map balance sheet items
                        bs_mapping = {
                            "equity and liabilities": None,
                            "share capital": "share_capital",
                            "total equity": "total_equity",
                            "total liabilities": "total_liabilities",
                            "reserve and surplus": "reserves",
                            "debt": "total_debt",
                            "borrowings": "total_debt",
                            "total assets": "total_assets",
                            "current assets": "current_assets",
                            "current liabilities": "current_liabilities",
                            "fixed assets": "fixed_assets",
                            "investments": "investments",
                            "cash and cash equivalents": "cash",
                            "cash and bank": "cash",
                        }

                        for key, target in bs_mapping.items():
                            if key in label and target:
                                data[target] = value

        except Exception as e:
            logger.debug(f"Failed to extract balance sheet: {e}")

        # Calculate current ratio if we have the data
        if "current_assets" in data and "current_liabilities" in data:
            if data["current_liabilities"] and data["current_liabilities"] > 0:
                data["current_ratio"] = data["current_assets"] / data["current_liabilities"]

        return data

    def _extract_cash_flow(self, soup: BeautifulSoup) -> dict:
        """Extract cash flow items."""
        data = {}

        try:
            tables = soup.find_all("table")

            for table in tables:
                rows = table.find_all("tr")
                for row in rows:
                    cells = row.find_all("td")
                    if len(cells) >= 2:
                        label = cells[0].get_text().strip().lower()
                        value_text = cells[-1].get_text().strip()
                        value = self._parse_financial_value(value_text)

                        cf_mapping = {
                            "operating cash flow": "operating_cash_flow",
                            "operating cash": "operating_cash_flow",
                            "free cash flow": "free_cash_flow",
                            "investing cash flow": None,
                            "financing cash flow": None,
                        }

                        for key, target in cf_mapping.items():
                            if key in label and target:
                                data[target] = value

        except Exception as e:
            logger.debug(f"Failed to extract cash flow: {e}")

        return data

    def _extract_profit_loss(self, soup: BeautifulSoup) -> dict:
        """Extract P&L items."""
        data = {}

        try:
            tables = soup.find_all("table")

            for table in tables:
                rows = table.find_all("tr")
                for row in rows:
                    cells = row.find_all("td")
                    if len(cells) >= 2:
                        label = cells[0].get_text().strip().lower()
                        value_text = cells[-1].get_text().strip()
                        value = self._parse_financial_value(value_text)

                        pl_mapping = {
                            "sales": "revenue",
                            "total income": "revenue",
                            "profit": "pat",
                            "net profit": "pat",
                            "profit after tax": "pat",
                            "pat": "pat",
                            "ebitda": "ebitda",
                            "ebit": "ebit",
                            "gross profit": "gross_profit",
                            "operating profit": "operating_profit",
                            "interest": "interest_expense",
                        }

                        for key, target in pl_mapping.items():
                            if key in label and target:
                                data[target] = value

        except Exception as e:
            logger.debug(f"Failed to extract P&L: {e}")

        return data

    def _parse_financial_value(self, value_str: str) -> Optional[float]:
        """
        Parse financial value from string.

        Handles formats like:
        - "1,234.56"
        - "123.45 Cr"
        - "1,234.56 L" (Lakhs)
        - "12,345.00 P" (Percent)
        """
        try:
            if not value_str or value_str == "---":
                return None

            # Remove currency symbols and commas
            cleaned = value_str.replace(",", "").replace(" ₹", "").replace("₹", "")

            # Handle suffixes
            multiplier = 1.0
            if " Cr" in cleaned or "cr" in cleaned.lower():
                multiplier = 100
                cleaned = cleaned.replace(" Cr", "").replace("cr", "").strip()
            elif " L" in cleaned or "l" in cleaned.lower():
                multiplier = 1
                cleaned = cleaned.replace(" L", "").replace("l", "").strip()
            elif "%" in cleaned:
                return float(cleaned.replace("%", "").strip())

            return float(cleaned) * multiplier

        except (ValueError, AttributeError):
            return None

    def _store_fundamentals(self, data: dict):
        """Store fundamentals in database."""
        try:
            with get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute(
                    """
                    INSERT OR REPLACE INTO fundamentals
                    (symbol, date_updated, pe_ratio, pb_ratio, dividend_yield,
                     roe, roce, roic, debt_to_equity, current_ratio,
                     sales_cagr_3y, sales_cagr_5y, profit_cagr_3y, profit_cagr_5y,
                     ocf_ttm, pat_ttm, revenue_ttm, book_value, source)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'yfinance')
                    """,
                    (
                        data.get("symbol"),
                        data.get("date_updated") or datetime.now().strftime("%Y-%m-%d"),
                        data.get("pe_ratio"),
                        data.get("pb_ratio"),
                        data.get("dividend_yield"),
                        data.get("roe"),
                        data.get("roce"),
                        data.get("roic"),
                        data.get("debt_to_equity"),
                        data.get("current_ratio"),
                        None,  # sales_cagr_3y - would need historical data
                        None,  # sales_cagr_5y
                        None,  # profit_cagr_3y
                        None,  # profit_cagr_5y
                        data.get("ocf_ttm"),
                        data.get("pat_ttm"),
                        data.get("revenue_ttm"),
                        data.get("book_value"),
                    ),
                )

                conn.commit()

        except Exception as e:
            logger.error(f"Failed to store fundamentals for {data.get('symbol')}: {e}")

    def scrape_all_ratios(self, symbol: str) -> dict:
        """
        Scrape comprehensive ratios from Screener's ratios page.

        Screener has a dedicated ratios section with more metrics.
        """
        try:
            url = f"{self.base_url}/company/{symbol}/ratios/"

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            }

            response = self.session.get(url, headers=headers, timeout=30)

            if response.status_code != 200:
                return {}

            soup = BeautifulSoup(response.text, "lxml")
            return self._parse_ratios_page(soup)

        except Exception as e:
            logger.error(f"Failed to scrape ratios page for {symbol}: {e}")
            return {}

    def _parse_ratios_page(self, soup: BeautifulSoup) -> dict:
        """Parse the dedicated ratios page."""
        ratios = {}

        try:
            # Screener's ratios page has a specific structure
            sections = soup.find_all("div", class_="row template-row")

            for section in sections:
                rows = section.find_all("div", class_="template-width-6")

                for row in rows:
                    cells = row.find_all("div")
                    if len(cells) >= 2:
                        label = cells[0].get_text().strip().lower()
                        value_text = cells[1].get_text().strip()

                        # Parse various ratio formats
                        if "%" in value_text:
                            value = float(value_text.replace("%", "").strip()) / 100
                        else:
                            value = self._parse_financial_value(value_text)

                        if value is not None:
                            ratios[label] = value

        except Exception as e:
            logger.debug(f"Failed to parse ratios page: {e}")

        return ratios