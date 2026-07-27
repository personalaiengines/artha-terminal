"""
ARTHA Terminal - Live Market News service

Pipeline (all live, no pre-populated cache required):
  1. Fetch  — open-source web search (SerpAPI primary → SearxNG fallback) across
              a few Indian-market queries. SearchService already caches results.
  2. Curate — an NVIDIA NIM model (free tier) ranks/dedupes the raw hits into the
              most market-relevant headlines, each with a one-line "why it matters".
              Strictly grounded: the model may only use the provided results.
  3. Fallback — if the LLM is unavailable, we still return the raw search hits so
                the feed is never empty when search worked.

Nothing here fabricates headlines or links — every item carries a real source URL
taken from the search results.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from config import config

# Fast NIM model — good enough for ranking/summarising, ~1-3s typical.
_NIM_MODEL = "meta/llama-3.1-8b-instruct"

# Queries span the whole market: indices, sectors, macro/policy, flows, earnings
# and corporate action — so the feed (and the UI category tabs) cover the full
# scope, not just headline indices. Each is one search credit, cached 6h.
_QUERIES = [
    "Indian stock market news today Nifty Sensex",
    "India sector stocks news today gainers losers banking IT pharma auto metals",
    "India markets FII DII institutional flows mutual fund inflows today",
    "India RBI monetary policy inflation CPI GDP rupee crude macro news today",
    "India company earnings results Q results dividend buyback merger acquisition IPO today",
    "India global markets cues US Fed Dow Nasdaq Asian markets impact today",
]


def _search(query: str, limit: int = 6) -> list[dict]:
    """Blocking wrapper around the async SearchService (SerpAPI → SearxNG)."""
    import asyncio
    from services.search import SearchService

    async def _go():
        try:
            return await SearchService().search(query, limit=limit, ttl_hours=6)
        except Exception:
            return []

    try:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_go())
        finally:
            loop.close()
    except Exception:
        return []


def _domain(url: str) -> str:
    """Publisher name from a URL, e.g. 'economictimes.indiatimes.com' -> 'Economictimes'."""
    m = re.search(r"https?://(?:www\.)?([^/]+)", url or "")
    if not m:
        return "Web"
    host = m.group(1).split(".")
    return (host[0] or "Web").capitalize()


def _gather() -> list[dict]:
    """Run all queries and dedupe by link, then by title."""
    seen_links: set[str] = set()
    seen_titles: set[str] = set()
    out: list[dict] = []
    for q in _QUERIES:
        for r in _search(q):
            link = (r.get("link") or "").strip()
            title = (r.get("title") or "").strip()
            if not title:
                continue
            tkey = title.lower()[:80]
            if (link and link in seen_links) or tkey in seen_titles:
                continue
            if link:
                seen_links.add(link)
            seen_titles.add(tkey)
            out.append({
                "title": title,
                "link": link,
                "snippet": (r.get("snippet") or "").strip(),
            })
    return out


def _nim_curate(raw: list[dict], limit: int) -> list[dict]:
    """Ask NIM to pick + summarise the most market-relevant headlines. [] on failure."""
    import httpx

    key = config.ai.nvidia_api_key
    if not key or not raw:
        return []

    lines = "\n".join(
        f"{i+1}. {r['title']} | {r['link']} | {r['snippet'][:160]}"
        for i, r in enumerate(raw[:30])
    )
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
    prompt = (
        f"Today is {today}. Below are web search results about Indian financial markets.\n\n"
        f"{lines}\n\n"
        f"Select the {limit} MOST market-relevant, distinct, recent items. Use ONLY the "
        f"results above — never invent headlines or links. For each, return an object:\n"
        f'{{"headline":"<concise, factual>","why":"<one line on why it matters to Indian '
        f'markets>","source_url":"<a link from above>","category":"<Markets|Stocks|Macro|'
        f'Policy|Global>"}}.\n'
        f"Return ONLY a JSON array, no preamble."
    )

    def _post() -> str:
        try:
            r = httpx.post(
                "https://integrate.api.nvidia.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": _NIM_MODEL,
                    "messages": [
                        {"role": "system", "content":
                            "You are a financial news editor for Indian markets. You rank and "
                            "summarise search results. You never fabricate facts, headlines, or "
                            "URLs — only use what is provided."},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": 1200, "temperature": 0.2,
                },
                timeout=45.0,
            )
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
        except Exception:
            return ""
        return ""

    valid_links = {r["link"] for r in raw if r.get("link")}

    def _parse(text: str) -> list[dict]:
        if not text:
            return []
        parsed = []
        m = re.search(r"\[.*\]", text, re.DOTALL)
        if m:
            try:
                parsed = json.loads(m.group(0))
            except Exception:
                parsed = []
        if not parsed:
            for b in re.findall(r"\{[^{}]*\}", text, re.DOTALL):
                try:
                    parsed.append(json.loads(b))
                except Exception:
                    continue
        items = []
        for it in parsed if isinstance(parsed, list) else []:
            if not isinstance(it, dict):
                continue
            head = str(it.get("headline", "")).strip()
            url = str(it.get("source_url", "")).strip()
            if not head or not url.startswith("http"):
                continue
            # Ground the link: keep only URLs the model actually saw.
            if url not in valid_links:
                # tolerate trailing-slash / query differences
                match = next((v for v in valid_links if v.rstrip("/").split("?")[0]
                              == url.rstrip("/").split("?")[0]), None)
                if not match:
                    continue
                url = match
            items.append({
                "title": head,
                "link": url,
                "snippet": str(it.get("why", "")).strip(),
                "source": str(it.get("category", "") or _domain(url)).strip(),
            })
        return items

    # NIM free tier is variable — retry the cheap curation a couple of times.
    for _ in range(2):
        items = _parse(_post())
        if items:
            return items[:limit]
    return []


def get_live_market_news(limit: int = 18) -> dict:
    """
    Live, LLM-curated Indian market news.

    Returns:
        {"items": [{title, link, snippet, source}], "ok": bool,
         "llm_used": bool, "generated_ist": iso, "count": int}
    Never caches an empty result (callers should not cache failures either).
    """
    raw = _gather()
    if not raw:
        return {"items": [], "ok": False, "llm_used": False,
                "generated_ist": datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(),
                "count": 0}

    curated = _nim_curate(raw, limit)
    llm_used = bool(curated)

    if not curated:
        # LLM unavailable — degrade gracefully to raw search hits.
        curated = [
            {"title": r["title"], "link": r["link"], "snippet": r["snippet"],
             "source": _domain(r["link"])}
            for r in raw[:limit]
        ]

    return {
        "items": curated,
        "ok": bool(curated),
        "llm_used": llm_used,
        "generated_ist": datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(),
        "count": len(curated),
    }


__all__ = ["get_live_market_news"]
