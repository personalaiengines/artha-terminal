"""
ARTHA Terminal - Market Events service
Forward-looking "what could move the market", split India / International, with
an external source link on every row.

Layered by reliability:
  1. Deterministic / API-sourced (always real, fast):
       • global economic calendar — Forex Factory weekly JSON feed. Every
         scheduled release for USD/EUR/GBP/JPY/AUD/CAD/CHF/NZD/CNY plus
         cross-market events (OPEC, G20), each with impact, forecast and prior.
       • India macro           — RBI's published MPC schedule (repo-rate
         decisions) plus MOSPI/DPIIT's advance release calendar (CPI, WPI,
         IIP, GDP). Forex Factory carries no INR, so without this the repo
         rate call — the single biggest event on an Indian desk — is missing.
       • India holidays        — Upstox /market/holidays
       • earnings              — yfinance, for tracked NSE symbols
       • NSE F&O expiry        — last-Thursday rule
       • international holidays — exchange_calendars
       • US Non-Farm Payrolls  — first-Friday rule
  2. AI-enriched macro (best-effort, cached): CPI / central-bank / GDP events
     extracted by the LLM ("quick" tier chain) from live SerpAPI results. Grounded on
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

from agent.prompts import COMPLIANCE, GROUNDING, HOUSE_STYLE

_SYSTEM = (
    f"{GROUNDING}\n\n{HOUSE_STYLE}\n\n{COMPLIANCE}\n\n"
    "You extract scheduled economic events from the web search results you were "
    "given. Return ONLY a JSON array — no prose, no preamble."
)



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


def _evt(d, kind, title, detail, url, region, **extra) -> dict:
    """One calendar row. `extra` carries the optional economic-release fields
    (time_ist / country / impact / forecast / previous) that only the Forex
    Factory feed supplies; the deterministic rows leave them unset and the UI
    falls back to deriving impact from `kind`."""
    return {"date": d, "kind": kind, "title": title,
            "detail": detail, "url": url, "region": region, **extra}


# ------------------------------------------------------------------
# Global economic calendar (Forex Factory weekly JSON)
# ------------------------------------------------------------------
#
# This is the layer that makes the page an actual economic calendar rather
# than a holiday list: every scheduled macro release across the major markets,
# already carrying impact / forecast / previous. Free, no key, no scraping —
# it is the JSON the Forex Factory calendar page itself consumes. Two files
# (this week + next week) cover the whole 14-day window the UI asks for.

_FF_URLS = (
    "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
    "https://nfs.faireconomy.media/ff_calendar_nextweek.json",
)
_FF_CAL = "https://www.forexfactory.com/calendar"
# The feed 403s httpx's default User-Agent, same as the publisher feeds in
# services/india_news.py.
_FF_UA = {"User-Agent": "Mozilla/5.0 (compatible; ARTHA-Terminal/1.0)"}

# Feed rows are tagged by currency, not country. "All" means cross-market
# (OPEC, G20). Everything else passes through as-is so a currency Forex
# Factory adds later still renders instead of vanishing.
_FF_COUNTRY = {"All": "GLB"}

# "Holiday" is Forex Factory's impact bucket for bank holidays — no number is
# released, so it ranks as low even though the market is shut.
_FF_IMPACT = {"high": "high", "medium": "medium", "low": "low", "holiday": "low"}

_IST = ZoneInfo("Asia/Kolkata")


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


def _ff_rows(raw: list, start: date, end: date) -> list[dict]:
    """Map one Forex Factory feed payload into calendar rows. Pure — the test
    feeds it a fixture, `_econ_calendar` feeds it the live JSON."""
    out = []
    for it in raw or []:
        if not isinstance(it, dict):
            continue
        title = str(it.get("title") or "").strip()
        try:
            # Feed stamps are ISO-8601 with a US/Eastern offset; the whole app
            # reads in IST, so normalise here rather than at every render site.
            ts = datetime.fromisoformat(str(it.get("date"))).astimezone(_IST)
        except Exception:
            continue
        if not title or not (start <= ts.date() <= end):
            continue
        cur = str(it.get("country") or "").strip()
        forecast = str(it.get("forecast") or "").strip() or None
        previous = str(it.get("previous") or "").strip() or None
        out.append(_evt(
            ts.date(), "econ", title,
            f"Prior {previous}" if previous else "Scheduled release",
            _FF_CAL, "international",
            time_ist=ts.strftime("%H:%M"),
            country=_FF_COUNTRY.get(cur, cur) or "GLB",
            impact=_FF_IMPACT.get(str(it.get("impact") or "").lower(), "medium"),
            forecast=forecast,
            previous=previous,
        ))
    return out


def _econ_calendar(days_ahead: int) -> list[dict]:
    """Every scheduled macro release in the window, across all covered markets.
    [] on any failure — the deterministic rows below never depend on it."""
    import httpx

    start, end = _today_ist(), _today_ist() + timedelta(days=days_ahead)
    events: list[dict] = []
    for url in _FF_URLS:
        try:
            r = httpx.get(url, headers=_FF_UA, timeout=15.0, follow_redirects=True)
            if r.status_code != 200:
                continue
            events += _ff_rows(r.json(), start, end)
        except Exception:
            continue
    return events


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


# ------------------------------------------------------------------
# India macro calendar (RBI + MOSPI published schedules)
# ------------------------------------------------------------------
#
# Forex Factory carries no INR, so without this layer the biggest events on an
# Indian desk's calendar — the repo-rate decision above all — simply never
# appear. Both sources publish their dates in advance, so these are recorded
# facts rather than predictions.

_RBI_MPC_URL = "https://website.rbi.org.in/web/rbi/monetary-policy"
_MOSPI_URL = "https://www.mospi.gov.in/release-calendar"
_WPI_URL = "https://eaindustry.nic.in/"

# RBI announces the whole fiscal year's MPC schedule in one press release (the
# FY2026-27 list below was published 2026-03-23). The committee sits for three
# days and the rate call lands on the last one — that final date is the one
# that moves the market, so it is the one dated here.
# ponytail: refresh once a year when RBI publishes the next FY schedule. A
# scraper for a six-row table that changes annually costs more than it saves,
# and RBI's own page is JS-rendered (the static HTML still serves 2020 rows).
_RBI_MPC_DATES = {
    date(2026, 4, 8): "Apr 6-8",
    date(2026, 6, 5): "Jun 3-5",
    date(2026, 8, 5): "Aug 3-5",
    date(2026, 10, 7): "Oct 5-7",
    date(2026, 12, 4): "Dec 2-4",
    date(2027, 2, 5): "Feb 3-5",
}

# MOSPI's advance release calendar fixes these to a day of the month. When the
# day is not a working day CPI slips forward but IIP pulls back — hence `roll`.
# (day_of_month, time_ist, roll, title, detail, url, impact)
_INDIA_MONTHLY = [
    (12, "16:00", +1, "India CPI inflation", "MOSPI consumer price index", _MOSPI_URL, "high"),
    (14, "12:00", +1, "India WPI inflation", "Wholesale price index", _WPI_URL, "medium"),
    (28, "16:00", -1, "India IIP", "Index of industrial production", _MOSPI_URL, "medium"),
]

# GDP lands on the last working day of these months (Q1 in Aug, Q2 in Nov,
# Q3 in Feb, Q4 plus the provisional annual estimate in May).
_GDP_MONTHS = {2: "Q3", 5: "Q4 + annual", 8: "Q1", 11: "Q2"}


def _roll_to_working_day(d: date, step: int) -> date:
    """Nudge off a weekend in `step`'s direction.

    ponytail: weekends only. Government holidays would need the DoPT list,
    which is not the NSE holiday list `_india_holidays` already fetches — a
    release can shift a day, and the source link on the row is the ground
    truth. Add the real list if a mis-dated row ever actually costs something.
    """
    while d.weekday() >= 5:
        d += timedelta(days=step)
    return d


def _india_macro_rows(start: date, end: date) -> list[dict]:
    """India's published macro calendar between two dates. Pure — the caller
    supplies the window so this stays testable without freezing the clock."""
    events = []

    for d, span in _RBI_MPC_DATES.items():
        if start <= d <= end:
            events.append(_evt(
                d, "policy", "RBI monetary policy decision",
                f"MPC meets {span} — repo rate call on the final day",
                _RBI_MPC_URL, "india",
                time_ist="10:00", country="IN", impact="high",
            ))

    # Walk every month the window touches, not just the current one: a 14-day
    # window starting on the 25th spills into the next month's releases.
    d = date(start.year, start.month, 1)
    while d <= end:
        for dom, tm, roll, title, detail, url, impact in _INDIA_MONTHLY:
            try:
                when = _roll_to_working_day(date(d.year, d.month, dom), roll)
            except ValueError:      # e.g. the 28th is fine, but stay safe
                continue
            if start <= when <= end:
                events.append(_evt(when, "macro", title, detail, url, "india",
                                   time_ist=tm, country="IN", impact=impact))

        if d.month in _GDP_MONTHS:
            last = date(d.year, d.month, 28)
            while (last + timedelta(days=1)).month == d.month:
                last += timedelta(days=1)
            last = _roll_to_working_day(last, -1)
            if start <= last <= end:
                events.append(_evt(
                    last, "macro", "India GDP",
                    f"{_GDP_MONTHS[d.month]} national accounts", _MOSPI_URL, "india",
                    time_ist="17:30", country="IN", impact="high",
                ))

        d = date(d.year + d.month // 12, d.month % 12 + 1, 1)

    return events


def _india_macro(days_ahead: int) -> list[dict]:
    return _india_macro_rows(_today_ist(), _today_ist() + timedelta(days=days_ahead))


# ------------------------------------------------------------------
# AI-enriched macro events (SerpAPI grounding + NVIDIA NIM extraction)
# ------------------------------------------------------------------

def _nim_extract(prompt: str, timeout: float = 40.0) -> str:
    """One completion through the router. Returns raw text or ''.

    `timeout` is accepted for call-site compatibility; the router owns per-tier
    timeouts now.
    """
    from agent.llm_client import complete

    # "quick": structured extraction from pre-fetched snippets, short JSON out.
    return complete(_SYSTEM, prompt, task_shape="quick")


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
    # Sort by time-of-day within the day too — an economic calendar that lists
    # the 18:00 Fed decision above the 06:00 PMI is not a calendar.
    events.sort(key=lambda e: (e["date"], e.get("time_ist") or ""))
    for e in events:
        if isinstance(e["date"], date):
            e["date"] = e["date"].isoformat()
        # Deterministic rows (holidays, expiry, earnings) carry no country tag;
        # give every row one so the UI never renders a blank badge.
        e.setdefault("country", "IN" if e["region"] == "india" else "GLB")
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

    india += _india_macro(days_ahead)
    india += _india_holidays(days_ahead)
    india += _earnings(symbols or [], days_ahead)
    intl += _econ_calendar(days_ahead)
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
