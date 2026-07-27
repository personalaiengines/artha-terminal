"""
ARTHA Terminal - Market Events service
Forward-looking "what could move the market", split India / International, with
an external source link on every row.

Layered by reliability:
  1. Deterministic / API-sourced (always real, fast):
       • India holidays        — Upstox /market/holidays
       • earnings              — yfinance, for tracked NSE symbols
       • NSE F&O expiry        — last-Thursday rule
       • international holidays — exchange_calendars
       • US Non-Farm Payrolls  — first-Friday rule
  2. AI-enriched macro (best-effort, cached): CPI / central-bank / GDP events
     extracted by an NVIDIA NIM model from live SerpAPI results. Grounded on
     real search snippets and always carries the source link, but the model can
     still err — rows are labelled "AI" so the user verifies via the link.

Curated authoritative calendar links per region are always returned so the full
macro calendar is one click away regardless of AI availability.
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from config import config


# ------------------------------------------------------------------
# Static reference data
# ------------------------------------------------------------------

# International exchange holidays to report (exchange_calendars code -> label)
_INTL_EXCHANGES = {
    "XNYS": ("US (NYSE)", "https://www.nyse.com/markets/hours-calendars"),
    "XLON": ("London (LSE)", "https://www.londonstockexchange.com/securities-trading/trading-access/business-days"),
    "XTKS": ("Tokyo (JPX)", "https://www.jpx.co.jp/english/corporate/about-jpx/calendar/"),
    "XHKG": ("Hong Kong (HKEX)", "https://www.hkex.com.hk/News/HKEX-Calendar"),
}

_NSE_HOLIDAY_URL = "https://www.nseindia.com/resources/exchange-communication-holidays"
_NSE_EXPIRY_URL = "https://www.nseindia.com/products-services/equity-derivatives-expiry-calendar"
_BLS_NFP_URL = "https://www.bls.gov/schedule/news_release/empsit.htm"
_SCREENER = "https://www.screener.in/company/{sym}/"

CALENDAR_LINKS = {
    "india": [
        {"label": "Zerodha markets calendar", "url": "https://zerodha.com/markets/calendar/"},
        {"label": "TradingEconomics · India", "url": "https://tradingeconomics.com/india/calendar"},
        {"label": "RBI press releases", "url": "https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx"},
        {"label": "NSE holidays", "url": _NSE_HOLIDAY_URL},
    ],
    "international": [
        {"label": "TradingEconomics · Global", "url": "https://tradingeconomics.com/calendar"},
        {"label": "Investing.com economic calendar", "url": "https://www.investing.com/economic-calendar/"},
        {"label": "Forex Factory calendar", "url": "https://www.forexfactory.com/calendar"},
        {"label": "US Federal Reserve calendar", "url": "https://www.federalreserve.gov/newsevents/calendar.htm"},
    ],
}


def _today_ist() -> date:
    return datetime.now(ZoneInfo("Asia/Kolkata")).date()


def _evt(d, kind, title, detail, url, region) -> dict:
    return {"date": d, "kind": kind, "title": title,
            "detail": detail, "url": url, "region": region}


# ------------------------------------------------------------------
# India holidays (Upstox, authoritative)
# ------------------------------------------------------------------

def _india_holidays(days_ahead: int) -> list[dict]:
    import asyncio
    from services.upstox import UpstoxClient

    start, end = _today_ist(), _today_ist() + timedelta(days=days_ahead)

    async def _go():
        return await UpstoxClient().get_market_holidays()

    try:
        loop = asyncio.new_event_loop()
        try:
            holidays = loop.run_until_complete(_go())
        finally:
            loop.close()
    except Exception:
        holidays = []

    events = []
    for h in holidays:
        try:
            d = date.fromisoformat(h["date"])
        except Exception:
            continue
        if start <= d <= end and "NSE" in (h.get("closed_exchanges") or []):
            events.append(_evt(d, "holiday", "NSE/BSE closed",
                               h.get("description", "Trading holiday"),
                               _NSE_HOLIDAY_URL, "india"))
    return events


# ------------------------------------------------------------------
# International holidays (exchange_calendars)
# ------------------------------------------------------------------

def _intl_holidays(days_ahead: int) -> list[dict]:
    try:
        import exchange_calendars as xc
        import pandas as pd
    except Exception:
        return []

    start, end = _today_ist(), _today_ist() + timedelta(days=days_ahead)
    events = []
    for code, (label, url) in _INTL_EXCHANGES.items():
        try:
            cal = xc.get_calendar(code)
            sessions = {ts.date() for ts in
                        cal.sessions_in_range(pd.Timestamp(start), pd.Timestamp(end))}
        except Exception:
            continue
        d = start
        while d <= end:
            if d.weekday() < 5 and d not in sessions:
                events.append(_evt(d, "holiday", f"{label} closed",
                                   "Exchange holiday", url, "international"))
            d += timedelta(days=1)
    return events


# ------------------------------------------------------------------
# Earnings (tracked NSE symbols)
# ------------------------------------------------------------------

def _one_earnings(symbol: str) -> dict | None:
    try:
        import yfinance as yf
        cal = yf.Ticker(f"{symbol}.NS").calendar
        ed = cal.get("Earnings Date") if isinstance(cal, dict) else None
        if ed:
            d = ed[0] if isinstance(ed, (list, tuple)) else ed
            if isinstance(d, datetime):
                d = d.date()
            return {"symbol": symbol, "date": d}
    except Exception:
        pass
    return None


def _earnings(symbols: list[str], days_ahead: int) -> list[dict]:
    if not symbols:
        return []
    start, end = _today_ist(), _today_ist() + timedelta(days=days_ahead)
    events = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for res in pool.map(_one_earnings, symbols):
            if res and start <= res["date"] <= end:
                events.append(_evt(res["date"], "earnings", f"{res['symbol']} results",
                                   "Quarterly earnings",
                                   _SCREENER.format(sym=res["symbol"]), "india"))
    return events


# ------------------------------------------------------------------
# Deterministic recurring events
# ------------------------------------------------------------------

def _last_weekday_of_month(y: int, mo: int, weekday: int) -> date:
    d = date(y, mo, 28)
    while (d + timedelta(days=1)).month == mo:
        d += timedelta(days=1)
    while d.weekday() != weekday:
        d -= timedelta(days=1)
    return d


def _nth_weekday_of_month(y: int, mo: int, weekday: int, n: int) -> date:
    d, count = date(y, mo, 1), 0
    while True:
        if d.weekday() == weekday:
            count += 1
            if count == n:
                return d
        d += timedelta(days=1)


def _recurring(days_ahead: int) -> list[dict]:
    start, end = _today_ist(), _today_ist() + timedelta(days=days_ahead)
    events = []
    for delta in (0, 1):
        mo = start.month + delta
        y, mo = start.year + (mo - 1) // 12, (mo - 1) % 12 + 1
        expiry = _last_weekday_of_month(y, mo, 3)  # last Thursday
        if start <= expiry <= end:
            events.append(_evt(expiry, "schedule", "NSE monthly F&O expiry",
                               "Derivatives settlement — elevated volatility",
                               _NSE_EXPIRY_URL, "india"))
        nfp = _nth_weekday_of_month(y, mo, 4, 1)  # first Friday
        if start <= nfp <= end:
            events.append(_evt(nfp, "schedule", "US Non-Farm Payrolls",
                               "Key US jobs data — global risk driver",
                               _BLS_NFP_URL, "international"))
    return events


# ------------------------------------------------------------------
# AI-enriched macro events (SerpAPI grounding + NVIDIA NIM extraction)
# ------------------------------------------------------------------

# Small fast NIM model for structured extraction (~1-3s vs ~90s for the 80B MoE).
# The heavier config.ai chain is reserved for quality-sensitive SWOT/verdict work.
_NIM_EXTRACT_MODEL = "meta/llama-3.1-8b-instruct"


def _nim_extract(prompt: str, timeout: float = 40.0) -> str:
    """One NVIDIA NIM completion (free tier). Returns raw text or ''."""
    import httpx
    key = config.ai.nvidia_api_key
    if not key:
        return ""
    try:
        r = httpx.post(
            "https://integrate.api.nvidia.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": _NIM_EXTRACT_MODEL,
                "messages": [
                    {"role": "system", "content":
                        "You extract scheduled economic events from web search results. "
                        "Return ONLY a JSON array. Never invent events or dates not present "
                        "in the provided results."},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 1500, "temperature": 0.1,
            },
            timeout=timeout,
        )
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"]
    except Exception:
        pass
    return ""


def _parse_ai_events(raw: str, region: str | None, days_ahead: int) -> list[dict]:
    """
    Parse + validate the model's JSON. Drops anything without a real date/link.
    If region is None, each item must carry its own "region" field.
    """
    if not raw:
        return []

    # Prefer a clean array parse; fall back to salvaging individual {...} objects
    # (the model output is often truncated at max_tokens with no closing "]").
    items: list = []
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    if m:
        try:
            items = json.loads(m.group(0))
        except Exception:
            items = []
    if not items:
        for obj in re.findall(r"\{[^{}]*\}", raw, re.DOTALL):
            try:
                items.append(json.loads(obj))
            except Exception:
                continue

    start, end = _today_ist(), _today_ist() + timedelta(days=days_ahead)
    out, seen = [], set()
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        try:
            d = date.fromisoformat(str(it.get("date"))[:10])
            title = str(it.get("title", "")).strip()
            url = str(it.get("source_url", "")).strip()
        except Exception:
            continue
        reg = region or ("india" if str(it.get("region", "")).lower().startswith("india")
                         else "international")
        key = (d, title.lower(), reg)
        if title and url.startswith("http") and start <= d <= end and key not in seen:
            seen.add(key)
            out.append(_evt(d, "macro", title,
                            str(it.get("detail", "")).strip()[:80] or "Scheduled release",
                            url, reg))
    return out[:14]


def _search_sync(query: str, limit: int = 6) -> list[dict]:
    """Blocking SerpAPI/SearxNG search."""
    import asyncio
    from services.search import SearchService

    async def _go():
        try:
            return await SearchService().search(query, limit=limit)
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


def get_ai_macro_events(days_ahead: int = 7) -> dict:
    """
    AI-enriched macro calendar (CPI / central banks / GDP) for both regions.

    Grounds a single NVIDIA NIM extraction on live SerpAPI results. Slow
    (~40-90s) and best-effort — callers should run it on demand and cache it.

    Returns {"india": [...], "international": [...], "ok": bool}.
    """
    india_res = _search_sync("India economic calendar this week RBI CPI GDP inflation data")
    intl_res = _search_sync("US Europe economic calendar this week CPI Fed FOMC ECB GDP jobs")

    def _fmt(results):
        return "\n".join(
            f"- {r.get('title','')} | {r.get('link','')} | {r.get('snippet','')}"
            for r in results
        )

    if not india_res and not intl_res:
        return {"india": [], "international": [], "ok": False}

    prompt = (
        f"Today is {_today_ist().isoformat()}. From the search results below, extract "
        f"scheduled market-moving economic events (central-bank meetings, CPI/inflation, "
        f"GDP, jobs, policy decisions) in the next {days_ahead} days.\n\n"
        f"INDIA results:\n{_fmt(india_res)}\n\n"
        f"INTERNATIONAL results:\n{_fmt(intl_res)}\n\n"
        f'Return ONLY a JSON array; each item: {{"date":"YYYY-MM-DD","region":"india"|'
        f'"international","title":"...","detail":"...","source_url":"<a link from above>"}}. '
        f"Only events with a clear date in the window. Max 14."
    )

    # NIM's free tier is variable — a call occasionally times out or returns
    # unparseable text. The searches are already cached, so retry the (cheap)
    # extraction up to 3 times before giving up.
    parsed = []
    for _ in range(3):
        raw = _nim_extract(prompt, timeout=45.0)
        parsed = _parse_ai_events(raw, region=None, days_ahead=days_ahead)
        if parsed:
            break

    return {
        "india": _finalize([e for e in parsed if e["region"] == "india"]),
        "international": _finalize([e for e in parsed if e["region"] == "international"]),
        "ok": bool(parsed),
    }


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def _finalize(events: list[dict]) -> list[dict]:
    events.sort(key=lambda e: e["date"])
    for e in events:
        if isinstance(e["date"], date):
            e["date"] = e["date"].isoformat()
    return events


def get_market_events(symbols: list[str] | None = None, days_ahead: int = 7) -> dict:
    """
    Assemble the fast, deterministic events split India / International, each row
    with a source link. AI macro events are fetched separately (get_ai_macro_events)
    because they are slow.

    Returns {"india": [...], "international": [...], "calendar_links": {...},
             "generated_ist": iso}.
    """
    india, intl = [], []

    india += _india_holidays(days_ahead)
    india += _earnings(symbols or [], days_ahead)
    intl += _intl_holidays(days_ahead)

    for e in _recurring(days_ahead):
        (india if e["region"] == "india" else intl).append(e)

    return {
        "india": _finalize(india),
        "international": _finalize(intl),
        "calendar_links": CALENDAR_LINKS,
        "generated_ist": datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(),
    }


__all__ = ["get_market_events", "get_ai_macro_events", "CALENDAR_LINKS"]
