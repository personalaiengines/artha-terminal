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


def _safe_err(e: Exception, *secrets: str | None) -> str:
    """Exception text with any credential scrubbed out.

    httpx puts the full request URL in its error message and SerpAPI takes its
    api_key as a *query parameter*, so an unredacted 429 wrote the live API key
    straight into the container log — and with the free quota spent, that was
    every search, every ten minutes, for anyone with `docker logs artha-api`.
    """
    msg = str(e)
    for secret in secrets:
        if secret:
            msg = msg.replace(secret, "***")
    return msg


class SearchService:
    """
    Search API client with primary/fallback support and smart caching.

    Primary:  SerpAPI (250 free searches/month)
    Then:     Jina s.jina.ai — real search, publisher's own URLs
    Then:     SearxNG self-hosted (unlimited, off unless SEARXNG_URL is set)
    Last:     Gemini with Google Search grounding — see _gemini_search for why
              this is a real search and not the model making things up.
    """

    def __init__(self):
        self.serpapi_key = config.search.serpapi_key
        self.searxng_url = config.search.searxng_url
        self.jina_api_key = config.search.jina_api_key
        # Lives on AIConfig, not SearchConfig — it is the same key the LLM tiers
        # use, and duplicating it into two config blocks would let them drift.
        self.google_api_key = config.ai.google_api_key

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
        results, source = await self._perform_search(query, limit, site)

        # Cache results
        if results:
            await self._cache_results(cache_key, query, site, results, ttl_hours, source)

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
        source: str = "unknown",
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
                        # The provider that actually answered. This used to be
                        # inferred from which key was configured, so every row
                        # said "serpapi" even when SerpAPI had 429'd and SearxNG
                        # served the results.
                        source,
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
    ) -> tuple[list[dict], str]:
        """Try each provider in order; return (results, the one that answered).

        Every rung is wrapped: a raised error used to abort the whole call, so
        the fallback never ran on the one failure it exists for. That applies to
        each rung, not just the first — an exception out of SearxNG would
        otherwise skip Gemini for exactly the same reason.

        Order is deliberate: the rungs that return the publisher's own URL come
        first. Gemini is last because it costs LLM quota and its links are Vertex
        grounding redirects rather than the real page.
        """
        # SerpAPI: 429s once the 250/month free quota is spent, which in practice
        # is most of the month.
        if self.serpapi_key:
            try:
                results = await self._serpapi_search(query, limit, site)
                if results:
                    return results, "serpapi"
            except Exception as e:
                print(f"SerpAPI search failed: {_safe_err(e, self.serpapi_key)}")

        # Jina is already the engine behind extract_url; s.jina.ai is the same
        # account's search surface, so this rung costs no new credential.
        if self.jina_api_key:
            try:
                results = await self._jina_search(query, limit, site)
                if results:
                    return results, "jina"
            except Exception as e:
                print(f"Jina search failed: {_safe_err(e, self.jina_api_key)}")

        if self.searxng_url and self.searxng_url != "http://localhost:8080":
            try:
                results = await self._searxng_search(query, limit, site)
                if results:
                    return results, "searxng"
            except Exception as e:
                print(f"SearxNG search failed: {_safe_err(e, self.searxng_url)}")

        if self.google_api_key:
            try:
                results = await self._gemini_search(query, limit, site)
                if results:
                    return results, "gemini"
            except Exception as e:
                print(f"Gemini grounded search failed: {_safe_err(e, self.google_api_key)}")

        return [], "none"

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

    async def _jina_search(
        self,
        query: str,
        limit: int,
        site: str | None,
    ) -> list[dict]:
        """Search using Jina (s.jina.ai).

        A real search over real pages, returning the publisher's own URL — which
        is why it outranks the Gemini rung, whose links are Vertex grounding
        redirects.

        `X-Respond-With: no-content` is the whole difference between a snippet
        and the entire scraped body of every hit. Without it Jina returns the
        full page text per result, which is megabytes for a ten-result query and
        swamps the token budget of everything downstream that reads this feed.

        Runs unauthenticated too, at a much lower rate limit; the key is the same
        one extract_url already uses.
        """
        full_query = f"{query} {site}" if site else query

        headers = {"Accept": "application/json", "X-Respond-With": "no-content"}
        if self.jina_api_key:
            headers["Authorization"] = f"Bearer {self.jina_api_key}"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://s.jina.ai/",
                params={"q": full_query},
                headers=headers,
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()

        return self._parse_jina(data, limit)

    @staticmethod
    def _parse_jina(data: dict, limit: int) -> list[dict]:
        """`{code, status, data: [{title, url, description, content}]}` into the
        one result shape every caller reads. Split out so it is testable without
        a network call, same as _parse_grounding."""
        results = []
        for r in (data.get("data") or []):
            if len(results) >= limit:
                break
            url = r.get("url")
            if not url:
                continue
            results.append({
                "title": r.get("title") or url,
                "link": url,
                # `content` is the full page when it is present at all; the
                # snippet belongs in description.
                "snippet": (r.get("description") or "")[:400],
            })
        return results

    async def _gemini_search(
        self,
        query: str,
        limit: int,
        site: str | None,
    ) -> list[dict]:
        """Last-resort search: Gemini with Google Search grounding.

        This is NOT the model answering from memory. The `google_search` tool
        makes Gemini run a real Google query, and the response carries
        `groundingMetadata` naming the actual pages it read. That metadata is the
        only thing this method returns — the model's own prose is used for
        snippets and nothing else.

        The distinction matters more here than anywhere else in the app. An
        invented headline with an invented-but-plausible URL is indistinguishable
        from a real one on screen, and this feed drives market-news curation for
        a terminal someone makes money decisions in. So: no groundingMetadata,
        no results. Never the model's unsourced text.

        Uses the native generateContent endpoint rather than the
        OpenAI-compatible surface agent/llm_client.py talks to — grounding is not
        exposed on the compatible one.
        """
        model = config.ai.google_model
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        full_query = f"{query} {site}" if site else query

        payload = {
            "contents": [{
                "parts": [{
                    "text": (
                        f"Search the web for: {full_query}\n\n"
                        "Report only what the sources actually say, one short sentence per source. "
                        "Do not add background knowledge of your own."
                    )
                }]
            }],
            "tools": [{"google_search": {}}],
            # Gemini spends tokens thinking before it answers, and they come out
            # of this budget — a small number returns finish_reason=length with
            # no content and no grounding at all.
            "generationConfig": {"maxOutputTokens": 2048, "temperature": 0.0},
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers={"x-goog-api-key": self.google_api_key, "Content-Type": "application/json"},
                json=payload,
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()

        return self._parse_grounding(data, limit)

    @staticmethod
    def _parse_grounding(data: dict, limit: int) -> list[dict]:
        """Real sources out of a Gemini grounded response, or nothing at all.

        Shape: `candidates[0].groundingMetadata.groundingChunks[].web.{uri,title}`
        for the pages, and `groundingSupports[]` mapping spans of the answer back
        to the chunks that support them — that mapping is what gives each link
        its own snippet instead of one shared blob of summary.

        Split out from the request so the guard that actually matters (ungrounded
        answer -> empty list) is testable without a network call.
        """
        candidates = data.get("candidates") or []
        if not candidates:
            return []

        meta = candidates[0].get("groundingMetadata") or {}
        chunks = meta.get("groundingChunks") or []
        if not chunks:
            # The model answered without searching. That is exactly the output
            # this service must never pass off as a search result.
            return []

        parts = (candidates[0].get("content") or {}).get("parts") or []
        answer = "".join(p.get("text", "") for p in parts)

        # chunk index -> the sentences of the answer that cited it
        snippets: dict[int, list[str]] = {}
        for support in meta.get("groundingSupports") or []:
            segment = support.get("segment") or {}
            text = segment.get("text")
            if not text:
                # Older payloads carry only byte offsets into the answer.
                text = answer[segment.get("startIndex", 0):segment.get("endIndex", 0)]
            text = text.strip()
            if not text:
                continue
            for i in support.get("groundingChunkIndices") or []:
                snippets.setdefault(i, []).append(text)

        results = []
        for i, chunk in enumerate(chunks):
            if len(results) >= limit:
                break
            web = chunk.get("web") or {}
            uri = web.get("uri")
            if not uri:
                continue  # a source with no link is not a search result
            results.append({
                "title": web.get("title") or uri,
                # A Vertex grounding-redirect URL, not the publisher's own. It
                # resolves to the real page but expires after ~30 days, which is
                # well past every TTL this service caches with.
                "link": uri,
                "snippet": " ".join(snippets.get(i, []))[:400],
            })
        return results

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


