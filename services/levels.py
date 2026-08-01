"""
ARTHA Terminal - prior-session price structure
Classic floor-trader pivots and the last settled daily candle for an index —
the price-structure half of the level map (services.fno_analysis supplies the
option-derived half and combines both into confluence zones).

These are standard technical levels (deterministic math on the previous
session's High/Low/Close), NOT price predictions and NOT buy/sell advice — the
same framing as the app's SEBI disclaimer.

Data: previous completed daily candle → yfinance (clean, settled OHLC).

Pruned deliberately: this module used to expose a second index-levels API
(get_index_levels / analyze / _analyst_view / get_pivot_bases / get_live_prices)
computing a `bias` from pivots ALONE under the same name as
fno_analysis.options_flow_bias — two truths, one word, no route calling either.
Its one good idea, rule-derived prose that never invents a number, is now
generalised across every level type by fno_analysis.level_zones /
structure_state. Only the pivot arithmetic below survives, because
services/fno_service.py imports it and it is the single implementation.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


def _classic_pivots(high: float, low: float, close: float) -> dict:
    """Classic (floor-trader) daily pivot levels."""
    p = (high + low + close) / 3
    rng = high - low
    return {
        "P": p,
        "R1": 2 * p - low, "R2": p + rng, "R3": high + 2 * (p - low),
        "S1": 2 * p - high, "S2": p - rng, "S3": low - 2 * (high - p),
    }


def _cpr(high: float, low: float, close: float) -> dict:
    """Central Pivot Range — the pivot plus the band around it that Indian
    intraday desks trade off. BC is the mid of the prior range, TC is the pivot
    reflected across it; which of the two ends up on top depends on the session,
    so they are returned already ordered."""
    p = (high + low + close) / 3
    bc = (high + low) / 2
    tc = 2 * p - bc
    return {"P": p, "top": max(tc, bc), "bottom": min(tc, bc)}


def _camarilla(high: float, low: float, close: float) -> dict:
    """Camarilla H3/L3 — the prior range scaled by 1.1/4 around the prior close.
    The pair most used intraday: price rejecting H3 or L3 is the classic
    mean-reversion read, price closing through it the breakout one."""
    rng = high - low
    return {"H3": close + rng * 1.1 / 4, "L3": close - rng * 1.1 / 4}


def _prior_week_hl(hist, today) -> dict | None:
    """High and low of the last COMPLETED calendar week, from a daily frame.

    Derived from the history already fetched rather than a second request. The
    current (unfinished) week is excluded on purpose — a "weekly high" that is
    still being made is not a level, it is a running maximum."""
    this_week = today.isocalendar()[:2]
    weeks: dict[tuple, list] = {}
    for idx, row in hist.iterrows():
        key = idx.date().isocalendar()[:2]
        if key >= this_week:
            continue
        weeks.setdefault(key, []).append(row)
    if not weeks:
        return None
    rows = weeks[max(weeks)]
    return {"high": max(float(r["High"]) for r in rows),
            "low": min(float(r["Low"]) for r in rows)}


def prior_structure(yf_ticker: str) -> dict | None:
    """Everything the level map takes from settled price history, in one fetch.

    Returns the last completed daily session (open/high/low/close), the classic
    pivots, the CPR band, the Camarilla H3/L3 pair and last week's range — or
    None when the history cannot be read. Every number here is arithmetic on
    settled OHLC: no forecast, no smoothing, nothing derived from a live tick.
    """
    try:
        import yfinance as yf
        hist = yf.Ticker(yf_ticker).history(period="2mo", interval="1d")
        if hist.empty:
            return None
        today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
        completed = [(idx, r) for idx, r in hist.iterrows() if idx.date() < today]
        sess_idx, row = completed[-1] if completed else (hist.index[-1], hist.iloc[-1])
        high, low, close = float(row["High"]), float(row["Low"]), float(row["Close"])
        return {
            "session": sess_idx.date().isoformat(),
            "open": float(row["Open"]), "high": high, "low": low, "close": close,
            "last_close": float(hist.iloc[-1]["Close"]),
            "pivots": _classic_pivots(high, low, close),
            "cpr": _cpr(high, low, close),
            "camarilla": _camarilla(high, low, close),
            "week": _prior_week_hl(hist, today),
        }
    except Exception:
        return None


__all__ = ["_classic_pivots", "_cpr", "_camarilla", "_prior_week_hl", "prior_structure"]
