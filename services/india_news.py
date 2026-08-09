"""
ARTHA Terminal - Indian market news (publisher RSS poll)

Why this exists: the Indian half of services/market_news.py was fed *only* by
web search (SerpAPI, then a SearxNG fallback that is unset by default). Once the
SerpAPI free quota is spent every Indian query returns [] — the searches 429 —
while the international side keeps working because it also polls Finnhub
directly. Result: a News page with a full Global tab and an empty India tab.

RSS is the fix that needs no key and no quota: the same publishers the feed
already bylines (Economic Times, Moneycontrol, Mint, Business Standard,
BusinessLine) put their markets desk on a public feed. Additive to search, same
shape as services/finnhub_news.py, so _gather dedupes it like any other source.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

logger = logging.getLogger("services.india_news")

# Markets desks, not the general national wire — the feed is a trading terminal's.
_FEEDS = [
    "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "https://www.livemint.com/rss/markets",
    "https://www.business-standard.com/rss/markets-106.rss",
    "https://www.thehindubusinessline.com/markets/feeder/default.rss",
    "https://www.moneycontrol.com/rss/business.xml",
]

# Publisher feeds serve a browser UA; some 403 the httpx default.
_UA = {"User-Agent": "Mozilla/5.0 (compatible; ARTHA-Terminal/1.0)"}

_TAGS = re.compile(r"<[^>]+>")


def _clean(text: str) -> str:
    """RSS <description> is HTML more often than not."""
    return _TAGS.sub(" ", text or "").replace("&nbsp;", " ").strip()


_DC_DATE = "{http://purl.org/dc/elements/1.1/}date"


def _published(item) -> str | None:
    """An <item>'s publication time as an ISO-8601 UTC string, or None.

    Every feed here emits RFC-2822 in <pubDate> ("Wed, 05 Aug 2026 05:47:27
    +0530"); some also carry ISO-8601 in Dublin Core <dc:date>. This was being
    dropped, which is most of why the news feed could not tell a story filed ten
    minutes ago from one filed in 2017 — nothing downstream had a date to sort
    or filter on.
    """
    raw = (item.findtext("pubDate") or item.findtext(_DC_DATE) or "").strip()
    if not raw:
        return None
    for parse in (parsedate_to_datetime, lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))):
        try:
            dt = parse(raw)
        except Exception:
            continue
        # A feed that omits the offset is quoting its own local time; treating
        # that as UTC is the conservative read (it ages the item, never
        # freshens it).
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    return None


def _one(url: str, per_feed: int) -> list[dict]:
    try:
        r = httpx.get(url, timeout=10.0, follow_redirects=True, headers=_UA)
        if r.status_code != 200:
            return []
        items = ET.fromstring(r.content).findall(".//item")
    except Exception as e:
        logger.warning(f"RSS fetch failed for {url}: {e}")
        return []

    out = []
    for it in items[:per_feed]:
        title = _clean(it.findtext("title") or "")
        link = (it.findtext("link") or "").strip()
        if not title or not link:
            continue
        out.append({
            "title": title,
            "link": link,
            "snippet": _clean(it.findtext("description") or "")[:300],
            "source": "rss",
            "published": _published(it),
        })
    return out


def get_india_market_news(per_feed: int = 8) -> list[dict]:
    """Recent Indian markets headlines from publisher RSS. [] on total failure —
    callers treat that the same as a search miss.

    ponytail: fetched fresh every call, no cache. RSS is free and each feed is
    one small GET; add a TTL only if the news job's cadence ever gets tight.
    """
    with ThreadPoolExecutor(max_workers=len(_FEEDS)) as pool:
        batches = pool.map(lambda u: _one(u, per_feed), _FEEDS)

    # Round-robin the publishers so a truncating caller doesn't end up with one
    # outlet's whole front page and nothing else.
    lists = [b for b in batches if b]
    out: list[dict] = []
    for i in range(max((len(b) for b in lists), default=0)):
        for b in lists:
            if i < len(b):
                out.append(b[i])
    return out


__all__ = ["get_india_market_news"]
