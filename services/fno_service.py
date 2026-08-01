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
from services.levels import prior_structure

# index key -> yfinance ticker for the settled prev-session OHLC / pivots
_YF = {"nifty50": "^NSEI", "banknifty": "^NSEBANK", "sensex": "^BSESN"}
INDEX_NAMES = {"nifty50": "NIFTY 50", "banknifty": "BANK NIFTY", "sensex": "SENSEX"}
INDEXES = ("nifty50", "banknifty", "sensex")

# After this IST time on an expiry day, the 0-DTE contract is stale for a
# next-session game plan → roll to the following expiry.
_ROLL_AFTER = (15, 30)

# The IV term structure costs one chain fetch per expiry (0.36-0.44s each,
# measured live). NIFTY lists 18 expiries; fetching them all would be ~7s on a
# page load for a curve nobody reads past the front end of. 4 caps it at ~1.8s
# and the payload states the cap so the curve is never read as the whole board.
TERM_STRUCTURE_N = 4


def _sync(coro):
    """Run one coroutine on a private loop — these wrappers are called from the
    API's thread pool, which has no running loop of its own."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _future_expiries(expiries: list[str]) -> list[str]:
    """Listed expiries today or later (IST), ascending. The expired tail Upstox
    still returns is not a choice a user can make."""
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    return [e for e in expiries if datetime.fromisoformat(e).date() >= today]


def _pick_expiry(expiries: list[str]) -> str | None:
    """
    First expiry >= today (IST); on expiry day, roll to the next one after ~15:30
    IST so the plan reflects the live contract, not the expiring 0-DTE.
    """
    if not expiries:
        return None
    future = _future_expiries(expiries)
    if not future:
        return None
    first = future[0]
    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    if datetime.fromisoformat(first).date() == now.date() and len(future) > 1:
        if (now.hour, now.minute) >= _ROLL_AFTER:
            return future[1]
    return first


async def _build_async(index: str, expiry: str | None = None) -> dict:
    key = FNO_UNDERLYINGS.get(index)
    if not key:
        return {"ok": False, "error": f"unknown index '{index}'", "index": index}

    client = UpstoxClient()
    expiries = await client.get_option_expiries(key)
    listed = _future_expiries(expiries)
    if expiry is not None and expiry not in listed:
        # `expiry` is user-controlled and would reach an upstream API. Validated
        # HERE — the one place every caller routes through — and before any chain
        # fetch, so the bogus value never leaves this process.
        return {"ok": False, "error": f"expiry '{expiry}' is not listed for {index}",
                "index": index, "expiries": listed}
    expiry = expiry or _pick_expiry(expiries)
    if not expiry:
        return {"ok": False, "error": "no option expiries available", "index": index}

    chain = await client.get_option_chain(key, expiry)
    if "error" in chain:
        return {"ok": False, "error": chain["error"], "index": index}

    vixq = await client.get_index_quotes(["indiavix"])
    vix = (vixq.get("indiavix") or {}).get("value") if isinstance(vixq, dict) else None

    # Prior settled session → pivots, CPR, Camarilla, PDH/PDL/close and last
    # week's range (yfinance, one fetch, best-effort).
    prior = prior_structure(_YF.get(index, ""))
    pivots = prior["pivots"] if prior else None
    prev = {"high": prior["high"], "low": prior["low"], "close": prior["close"]} if prior else None

    plan = fno.analyze(chain, prev_ohlc=prev, vix=vix, pivots=pivots, structure=prior)
    plan["index"] = index
    plan["name"] = INDEX_NAMES.get(index, index)
    plan["generated_ist"] = datetime.now(ZoneInfo("Asia/Kolkata")).isoformat()
    # keep the raw strikes for the OI chart (page-side)
    plan["strikes"] = chain.get("strikes", [])
    # Every expiry a user may switch to, so the selector costs no round-trip.
    plan["expiries"] = listed
    return plan


def build_game_plan(index: str, expiry: str | None = None) -> dict:
    """Sync wrapper — full F&O game plan for one index (self-contained event loop).

    `expiry` ("YYYY-MM-DD") selects a listed non-nearest expiry; unlisted values
    are rejected without an upstream call. Default = the nearest live contract."""
    try:
        return _sync(_build_async(index, expiry))
    except Exception as e:
        return {"ok": False, "error": str(e), "index": index}


def get_expiries(index: str) -> dict:
    """Every expiry a user can pick for one index, plus the one the plan defaults
    to. Ascending, today or later."""
    key = FNO_UNDERLYINGS.get(index)
    if not key:
        return {"ok": False, "error": f"unknown index '{index}'", "index": index, "expiries": []}
    try:
        raw = _sync(UpstoxClient().get_option_expiries(key))
    except Exception as e:
        return {"ok": False, "error": str(e), "index": index, "expiries": []}
    listed = _future_expiries(raw)
    return {"ok": bool(listed), "index": index, "name": INDEX_NAMES.get(index, index),
            "expiries": listed, "default": _pick_expiry(raw),
            **({} if listed else {"error": "no option expiries available"})}


async def _term_async(index: str, n: int) -> dict:
    key = FNO_UNDERLYINGS.get(index)
    if not key:
        return {"ok": False, "error": f"unknown index '{index}'", "index": index, "points": []}
    client = UpstoxClient()
    picked = _future_expiries(await client.get_option_expiries(key))[:n]
    if not picked:
        return {"ok": False, "error": "no option expiries available",
                "index": index, "points": []}

    chains = await asyncio.gather(*(client.get_option_chain(key, e) for e in picked))
    points, unpriced = [], []
    for exp, chain in zip(picked, chains):
        strikes = chain.get("strikes") or []
        iv = fno.atm_iv(chain.get("spot"), strikes)
        if iv is None:
            # The chain failed, or Upstox never priced its ATM legs (a literal
            # 0.0 greek is parsed as absent). Named, never plotted as a zero.
            unpriced.append(exp)
            continue
        points.append({"expiry": exp, "atm": fno.atm_strike(chain.get("spot"), strikes),
                       "atm_iv": round(iv, 2), "spot": chain.get("spot")})
    return {"ok": bool(points), "index": index, "name": INDEX_NAMES.get(index, index),
            "cap": n, "points": points, "unpriced": unpriced,
            # False = a partial read. Callers must not cache it as a good one.
            "complete": len(points) == len(picked)}


def term_structure(index: str, n: int = TERM_STRUCTURE_N) -> dict:
    """ATM IV per expiry across the nearest `n` expiries — the IV term structure.

    Capped deliberately (see TERM_STRUCTURE_N); `cap` travels in the payload so
    the UI can say so. An expiry whose ATM legs carry no live IV is listed in
    `unpriced` and `complete` goes False, rather than being drawn as 0."""
    try:
        return _sync(_term_async(index, n))
    except Exception as e:
        return {"ok": False, "error": str(e), "index": index, "points": []}


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


__all__ = ["build_game_plan", "get_expiries", "term_structure",
           "get_index_intraday", "get_index_history",
           "INDEX_NAMES", "INDEXES", "TERM_STRUCTURE_N"]
