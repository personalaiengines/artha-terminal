"""
ARTHA Terminal - F&O orchestration
Fetch the live inputs (option chain, India VIX, prior-session pivots) and produce
the daily options game plan per index. Pure math lives in services.fno_analysis;
this layer does the I/O and is reused by the ARTHA page and the daily scheduler.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from services.upstox import UpstoxClient, FNO_UNDERLYINGS
from services import fno_analysis as fno
from services.levels import _prev_session_ohlc, _classic_pivots

# index key -> yfinance ticker for the settled prev-session OHLC / pivots
_YF = {"nifty50": "^NSEI", "banknifty": "^NSEBANK", "sensex": "^BSESN"}
INDEX_NAMES = {"nifty50": "NIFTY 50", "banknifty": "BANK NIFTY", "sensex": "SENSEX"}
INDEXES = ("nifty50", "banknifty", "sensex")

# After this IST time on an expiry day, the 0-DTE contract is stale for a
# next-session game plan → roll to the following expiry.
_ROLL_AFTER = (15, 30)


def _pick_expiry(expiries: list[str]) -> str | None:
    """
    First expiry >= today (IST); on expiry day, roll to the next one after ~15:30
    IST so the plan reflects the live contract, not the expiring 0-DTE.
    """
    if not expiries:
        return None
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    future = [e for e in expiries if datetime.fromisoformat(e).date() >= today]
    if not future:
        return None
    first = future[0]
    if datetime.fromisoformat(first).date() == today and len(future) > 1:
        now = datetime.now(ZoneInfo("Asia/Kolkata"))
        if (now.hour, now.minute) >= _ROLL_AFTER:
            return future[1]
    return first


async def _build_async(index: str) -> dict:
    key = FNO_UNDERLYINGS.get(index)
    if not key:
        return {"ok": False, "error": f"unknown index '{index}'", "index": index}

    client = UpstoxClient()
    expiries = await client.get_option_expiries(key)
    expiry = _pick_expiry(expiries)
    if not expiry:
        return {"ok": False, "error": "no option expiries available", "index": index}

    chain = await client.get_option_chain(key, expiry)
    if "error" in chain:
        return {"ok": False, "error": chain["error"], "index": index}

    vixq = await client.get_index_quotes(["indiavix"])
    vix = (vixq.get("indiavix") or {}).get("value") if isinstance(vixq, dict) else None

    # Prior settled session → classic pivots + PDH/PDL (yfinance, best-effort).
    pivots = prev = None
    ohlc = _prev_session_ohlc(_YF.get(index, ""))
    if ohlc:
        _, high, low, close, _ = ohlc
        pivots = _classic_pivots(high, low, close)
        prev = {"high": high, "low": low}

    plan = fno.analyze(chain, prev_ohlc=prev, vix=vix, pivots=pivots)
    plan["index"] = index
    plan["name"] = INDEX_NAMES.get(index, index)
    plan["generated_ist"] = datetime.now(ZoneInfo("Asia/Kolkata")).isoformat()
    # keep the raw strikes for the OI chart (page-side)
    plan["strikes"] = chain.get("strikes", [])
    return plan


def build_game_plan(index: str) -> dict:
    """Sync wrapper — full F&O game plan for one index (self-contained event loop)."""
    try:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_build_async(index))
        finally:
            loop.close()
    except Exception as e:
        return {"ok": False, "error": str(e), "index": index}


def get_index_intraday(index: str, interval: str = "1minute") -> list[list]:
    """Sync wrapper — today's live intraday candles for one index ([] on failure)."""
    key = FNO_UNDERLYINGS.get(index)
    if not key:
        return []

    async def _f():
        return await UpstoxClient().get_intraday_candles(key, interval)

    try:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_f())
        finally:
            loop.close()
    except Exception:
        return []


# Upstox caps the date range per request for fine intervals. Page in windows no
# larger than the cap so 15m/30m can still span a full year (stitched together).
_HIST_WINDOW = {"1minute": 25, "30minute": 150}   # days/request; others = single shot


def get_index_history(index: str, interval: str = "day", days: int = 400) -> list[list]:
    """Sync wrapper — historical candles for one index over the last `days`, PAGED
    in cap-sized windows for fine intervals so 15m/30m reach ~1 year ([] on error)."""
    key = FNO_UNDERLYINGS.get(index)
    if not key:
        return []
    to_d = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    from_d = to_d - timedelta(days=days)
    win = _HIST_WINDOW.get(interval)

    async def _f():
        client = UpstoxClient()
        if not win:
            return await client.get_candles(key, interval, from_d.isoformat(), to_d.isoformat())
        rows: list[list] = []
        cur_to = to_d
        while cur_to >= from_d:
            cur_from = max(from_d, cur_to - timedelta(days=win))
            rows += await client.get_candles(
                key, interval, cur_from.isoformat(), cur_to.isoformat()
            )
            cur_to = cur_from - timedelta(days=1)
        return rows

    try:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_f())
        finally:
            loop.close()
    except Exception:
        return []


__all__ = ["build_game_plan", "get_index_intraday", "get_index_history",
           "INDEX_NAMES", "INDEXES"]
