"""
ARTHA Terminal - Search Service
SerpAPI and SearxNG search integration with caching.
"""

import httpx
import json
import hashlib
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
import sqlite3

from config import config
from db import get_connection


class SearchService:
    """
    Search API client with primary/fallback support and smart caching.

    Primary: SerpAPI (250 free searches/month)
    Fallback: SearxNG self-hosted (unlimited)
    """

    def __init__(self):
        self.serpapi_key = config.search.serpapi_key
        self.searxng_url = config.search.searxng_url
        self.jina_api_key = config.search.jina_api_key

    def _get_cache_key(self, query: str, site: str | None = None) -> str:
        """Generate cache key from query."""
        key_str = f"{query}:{site or ''}"
        return hashlib.md5(key_str.encode()).hexdigest()

    async def search(
        self,
        query: str,
        limit: int = 10,
        site: str | None = None,
        ttl_hours: int = 48,
    ) -> list[dict]:
        """
        Perform web search with automatic caching.

        Args:
            query: Search query
            limit: Number of results
            site: Optional site filter (e.g., "site:screener.in")
            ttl_hours: Cache TTL in hours

        Returns:
            List of search results
        """
        cache_key = self._get_cache_key(query, site)

        # Check cache first
        cached = await self._get_from_cache(cache_key)
        if cached:
            print(f"Cache hit: {query[:30]}...")
            return cached

        print(f"Searching: {query[:50]}...")

        # Perform fresh search
        results = await self._perform_search(query, limit, site)

        # Cache results
        if results:
            await self._cache_results(cache_key, query, site, results, ttl_hours)

        return results

    async def _get_from_cache(self, cache_key: str) -> list[dict] | None:
        """Check if results are cached and not expired."""
        try:
            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT results_json FROM search_cache
                    WHERE key = ? AND datetime(expires_at) > datetime('now')
                    ORDER BY cache_at DESC
                    LIMIT 1
                    """,
                    (cache_key,)
                )
                row = cursor.fetchone()

                if row:
                    return json.loads(row[0])
        except Exception as e:
            print(f"Cache check failed: {e}")

        return None

    async def _cache_results(
        self,
        cache_key: str,
        query: str,
        site: str | None,
        results: list[dict],
        ttl_hours: int,
    ):
        """Cache search results."""
        try:
            now = datetime.now()
            expires = now + timedelta(hours=ttl_hours)

            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO search_cache
                    (key, query, sector, symbol, results_json, source,
                     cache_at, ttl_hours, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cache_key,
                        query,
                        None,  # sector
                        None,  # symbol
                        json.dumps(results),
                        "serpapi" if self.serpapi_key else "searxng",
                        now.isoformat(),
                        ttl_hours,
                        expires.isoformat(),
                    )
                )
                conn.commit()
        except Exception as e:
            print(f"Cache write failed: {e}")

    async def _perform_search(
        self,
        query: str,
        limit: int,
        site: str | None
    ) -> list[dict]:
        """Perform actual search using available providers."""
        results = []

        # Try SerpAPI first
        if self.serpapi_key:
            results = await self._serpapi_search(query, limit, site)
            if results:
                return results

        # Fall back to SearxNG
        if self.searxng_url and self.searxng_url != "http://localhost:8080":
            results = await self._searxng_search(query, limit, site)

        return results

    async def _serpapi_search(
        self,
        query: str,
        limit: int,
        site: str | None,
    ) -> list[dict]:
        """Search using SerpAPI."""
        url = "https://serpapi.com/search"

        full_query = query
        if site:
            full_query = f"{query} {site}"

        params = {
            "api_key": self.serpapi_key,
            "q": full_query,
            "num": limit,
            "engine": "google",
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=15.0)
            response.raise_for_status()
            data = response.json()

        return [
            {
                "title": r.get("title", ""),
                "link": r.get("link", ""),
                "snippet": r.get("snippet", ""),
            }
            for r in data.get("organic_results", [])[:limit]
        ]

    async def _searxng_search(
        self,
        query: str,
        limit: int,
        site: str | None,
    ) -> list[dict]:
        """Search using self-hosted SearxNG."""
        url = f"{self.searxng_url}/search"

        full_query = query
        if site:
            full_query = f"{query} {site}"

        params = {
            "q": full_query,
            "format": "json",
            "pageno": 1,
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=15.0)
            response.raise_for_status()
            data = response.json()

        return [
            {
                "title": r.get("title", ""),
                "link": r.get("url", ""),
                "snippet": r.get("content", ""),
            }
            for r in data.get("results", [])[:limit]
        ]

    async def extract_url(self, url: str) -> str:
        """
        Extract full page content from a URL using Jina AI reader.
        """
        headers = {"Accept": "application/text"}
        if self.jina_api_key:
            headers["Authorization"] = f"Bearer {self.jina_api_key}"

        jina_url = f"https://r.jina.ai/{url}"

        async with httpx.AsyncClient() as client:
            response = await client.get(jina_url, headers=headers, timeout=30.0)
            response.raise_for_status()
            return response.text


# ============================================
# Helper Functions for AI Tools
# ============================================

async def sector_news(sector: str, limit: int = 10) -> dict:
    """
    Fetch recent news headlines for a sector.
   Cached for 24 hours.
    """
    service = SearchService()

    results = await service.search(
        query=f"{sector} sector India stock market news",
        limit=limit,
        ttl_hours=24,
    )

    return {
        "sector": sector,
        "news": results,
        "count": len(results),
    }


async def stock_news(symbol: str, limit: int = 5) -> dict:
    """
    Fetch recent news for a specific stock.
    Cached for 12 hours.
    """
    service = SearchService()

    results = await service.search(
        query=f"{symbol} RELIANCE TCS",
        limit=limit,
        ttl_hours=12,
    )

    return {
        "symbol": symbol,
        "news": results,
        "count": len(results),
    }


async def get_company_info(query: str) -> dict:
    """
    Search for company information.
    Cached for 7 days.
    """
    service = SearchService()

    results = await service.search(
        query=f"{query} company profile business model India",
        limit=5,
        ttl_hours=168,  # 7 days
    )

    return {
        "query": query,
        "info": results,
    }