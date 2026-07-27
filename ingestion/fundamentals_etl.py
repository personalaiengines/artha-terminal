"""
ARTHA Terminal - Fundamentals ETL
Extracts company financial data from Screener.in.

Sources:
- Screener.in (SEBI-registered data aggregator)
- NSE/BSE filings (for verified data)
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
        self.request_delay = 2.0  # Be polite - 2 second delay between requests

    def run(
        self,
        symbols: List[str] | None = None,
        max_per_run: int = 50,
    ) -> dict:
        """
        Run fundamentals ETL.

        Args:
            symbols: Specific symbols to update (None = all tracked)
            max_per_run: Maximum symbols to process per run

        Returns:
            ETL statistics
        """
        logger.info("Starting Fundamentals ETL...")

        stats = {
            "symbols_processed": 0,
            "symbols_updated": 0,
            "errors": 0,
            "rate_limited": 0,
        }

        try:
            # Get symbols to process
            if symbols:
                target_symbols = symbols
            else:
                target_symbols = self._get_tracked_symbols()

            # Limit per run to avoid overwhelming sources
            target_symbols = target_symbols[:max_per_run]

            logger.info(f"Processing {len(target_symbols)} symbols")

            for symbol in target_symbols:
                result = self._process_symbol(symbol)
                stats["symbols_processed"] += 1

                if result["status"] == "success":
                    stats["symbols_updated"] += 1
                else:
                    stats["errors"] += 1

                # Polite delay
                time.sleep(self.request_delay)

            logger.info("Fundamentals ETL completed")
            return {"status": "success", **stats}

        except Exception as e:
            logger.error(f"Fundamentals ETL failed: {e}")
            return {"status": "error", "error": str(e), **stats}

    def _get_tracked_symbols(self) -> List[str]:
        """Get list of symbols in database."""
        try:
            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT symbol FROM symbol_master
                    WHERE symbol IS NOT NULL
                    LIMIT 100
                """)
                return [row["symbol"] for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to get tracked symbols: {e}")
            return []

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

    def _extract_company_info(self, soup: BeautifulSoup, symbol: str) -> dict:
        """Extract basic company information."""
        try:
            # Company name
            name_elem = soup.find("title")
            company_name = name_elem.get_text().split("-")[0].strip() if name_elem else symbol

            # Get sector/industry from page
            # Screener shows structure like: Home > Equity > SECTOR > COMPANY
            breadcrumb = soup.find("ul", class_="breadcrumb")
            sector = None
            industry = None

            if breadcrumb:
                links = breadcrumb.find_all("a")
                if len(links) >= 3:
                    sector = links[-2].get_text().strip()
                    industry = links[-1].get_text().strip()

            return {
                "company_name": company_name,
                "sector": sector,
                "industry": industry,
            }
        except Exception as e:
            logger.debug(f"Failed to extract company info: {e}")
            return {}

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
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'screener')
                    """,
                    (
                        data.get("symbol"),
                        data.get("date_updated"),
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
                        data.get("operating_cash_flow"),
                        data.get("pat"),
                        data.get("revenue"),
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