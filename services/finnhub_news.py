"""
ARTHA Terminal - Finnhub general market news (REST poll)

Correction vs. the original plan: Finnhub's free tier does NOT push news over
its WebSocket — that stream only carries real-time trade prices (and mostly
for US-listed symbols; NSE/BSE aren't covered on the free tier, so it isn't
useful here for price streaming either, which Upstox's WS already handles
correctly for Indian markets). News is REST-only: GET /news?category=general.

So this polls that REST endpoint (free tier: 60 req/min, plenty for a job
that runs every ~10 min) instead of subscribing to a nonexistent news
channel. It's additive to services/market_news.py's SerpAPI/SearxNG cycle,
not a replacement.
"""

from __future__ import annotations

import logging

import httpx

from config import config

logger = logging.getLogger("services.finnhub_news")

_URL = "https://finnhub.io/api/v1/news"


def get_finnhub_general_news(limit: int = 20) -> list[dict]:
    """Recent general-market headlines from Finnhub. [] if unconfigured or on
    any failure — callers already treat an empty list as "this source had
    nothing", same as a SerpAPI miss."""
    key = config.search.finnhub_api_key
    if not key:
        return []
    try:
        r = httpx.get(_URL, params={"category": "general", "token": key}, timeout=10.0)
        if r.status_code != 200:
            return []
        raw = r.json()
    except Exception as e:
        logger.warning(f"Finnhub news fetch failed: {e}")
        return []

    out = []
    for item in (raw or [])[:limit]:
        headline = (item.get("headline") or "").strip()
        url = (item.get("url") or "").strip()
        if not headline or not url:
            continue
        out.append({
            "title": headline,
            "link": url,
            "snippet": (item.get("summary") or "").strip(),
            "source": "finnhub",
        })
    return out
