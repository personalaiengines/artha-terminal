"""
ARTHA Terminal - Index Levels service
Support/resistance and a senior-analyst-style read for NIFTY 50, BANK NIFTY and
SENSEX, computed from real OHLC via classic daily pivot points.

These are standard technical levels (deterministic math on the previous
session's High/Low/Close), NOT price predictions and NOT buy/sell advice — the
same framing as the app's SEBI disclaimer. The "analyst view" narrative is
rule-derived from the computed levels, so it never invents a number.

Data:
  • previous completed daily candle → yfinance (clean, settled OHLC)
  • current live price              → Upstox index quotes, yfinance fallback
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


INDICES = [
    {"key": "nifty50", "name": "NIFTY 50", "yf": "^NSEI", "upstox": "nifty50"},
    {"key": "banknifty", "name": "BANK NIFTY", "yf": "^NSEBANK", "upstox": "banknifty"},
    {"key": "sensex", "name": "SENSEX", "yf": "^BSESN", "upstox": "sensex"},
]


def _classic_pivots(high: float, low: float, close: float) -> dict:
    """Classic (floor-trader) daily pivot levels."""
    p = (high + low + close) / 3
    rng = high - low
    return {
        "P": p,
        "R1": 2 * p - low, "R2": p + rng, "R3": high + 2 * (p - low),
        "S1": 2 * p - high, "S2": p - rng, "S3": low - 2 * (high - p),
    }


def _prev_session_ohlc(yf_ticker: str):
    """(session_date, high, low, close, last_close) from the last completed candle."""
    try:
        import yfinance as yf
        hist = yf.Ticker(yf_ticker).history(period="7d", interval="1d")
        if hist.empty:
            return None
        today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
        completed = [(idx, r) for idx, r in hist.iterrows() if idx.date() < today]
        sess_idx, row = completed[-1] if completed else (hist.index[-1], hist.iloc[-1])
        last_close = float(hist.iloc[-1]["Close"])
        return (sess_idx.date().isoformat(), float(row["High"]),
                float(row["Low"]), float(row["Close"]), last_close)
    except Exception:
        return None


def _live_prices() -> dict:
    """Current index values from Upstox (best-effort)."""
    import asyncio
    from services.upstox import UpstoxClient

    async def _go():
        return await UpstoxClient().get_index_quotes()

    try:
        loop = asyncio.new_event_loop()
        try:
            q = loop.run_until_complete(_go())
        finally:
            loop.close()
        if isinstance(q, dict) and "error" not in q:
            return {k: v.get("value") for k, v in q.items() if v.get("value")}
    except Exception:
        pass
    return {}


def _nearest(levels: list[tuple[str, float]], price: float) -> tuple[tuple, tuple]:
    """Return (nearest_support, nearest_resistance) as (label, value) tuples."""
    below = [lv for lv in levels if lv[1] < price]
    above = [lv for lv in levels if lv[1] > price]
    support = max(below, key=lambda x: x[1]) if below else None
    resistance = min(above, key=lambda x: x[1]) if above else None
    return support, resistance


def _ladder(piv: dict) -> list[tuple[str, float]]:
    return [("S3", piv["S3"]), ("S2", piv["S2"]), ("S1", piv["S1"]),
            ("Pivot", piv["P"]), ("R1", piv["R1"]), ("R2", piv["R2"]), ("R3", piv["R3"])]


def _analyst_view(name: str, price: float, piv: dict) -> str:
    """Rule-derived senior-analyst narrative from the computed levels."""
    support, resistance = _nearest(_ladder(piv), price)

    if price > piv["R3"]:
        parts = [f"{name} at {price:,.0f} is in a breakout zone, trading above all "
                 f"pivot resistances (R3 {piv['R3']:,.0f}), which now flips to immediate "
                 f"support. With no overhead pivot resistance, momentum favours the bulls "
                 f"as long as it holds R3; a slip back below R3 would signal exhaustion."]
        return " ".join(parts)
    if price < piv["S3"]:
        parts = [f"{name} at {price:,.0f} is in a breakdown zone, below all pivot "
                 f"supports (S3 {piv['S3']:,.0f}), which now acts as immediate resistance. "
                 f"Sentiment stays weak until it reclaims S3; a recovery above it would be "
                 f"the first sign of stabilisation."]
        return " ".join(parts)

    if price > piv["P"]:
        bias = "constructive — trading above the daily pivot"
    elif price < piv["P"]:
        bias = "cautious — trading below the daily pivot"
    else:
        bias = "balanced — hovering at the daily pivot"

    parts = [f"{name} at {price:,.0f} looks {bias}."]
    if resistance:
        parts.append(
            f"Immediate resistance is {resistance[0]} near {resistance[1]:,.0f} "
            f"(+{(resistance[1] - price) / price * 100:.1f}%); a sustained close above it "
            f"opens the next leg higher."
        )
    if support:
        parts.append(
            f"On dips, {support[0]} around {support[1]:,.0f} "
            f"({(support[1] - price) / price * 100:.1f}%) is the first cushion; "
            f"losing it shifts momentum lower."
        )
    return " ".join(parts)


def get_pivot_bases() -> dict:
    """
    Daily pivot levels per index — the SLOW, once-a-day part. Depends only on the
    previous completed session's OHLC, so it is stable through the whole trading
    day and safe to cache for a long time.

    Returns {"indices": [{key, name, session_date, pivot, resistances[],
             supports[], _piv}], "computed_ist": iso}.
    """
    out = []
    for idx in INDICES:
        ohlc = _prev_session_ohlc(idx["yf"])
        if not ohlc:
            continue
        session_date, high, low, close, yf_last = ohlc
        piv = _classic_pivots(high, low, close)
        out.append({
            "key": idx["upstox"],
            "name": idx["name"],
            "session_date": session_date,
            "yf_last": round(yf_last, 2),
            "pivot": round(piv["P"], 2),
            "resistances": [("R1", round(piv["R1"])), ("R2", round(piv["R2"])), ("R3", round(piv["R3"]))],
            "supports": [("S1", round(piv["S1"])), ("S2", round(piv["S2"])), ("S3", round(piv["S3"]))],
            "_piv": {k: round(v, 2) for k, v in piv.items()},
        })
    return {
        "indices": out,
        "computed_ist": datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(),
    }


def get_live_prices() -> dict:
    """
    Current index prices — the FAST, per-minute part.

    Returns {"prices": {key: value}, "live_keys": [keys from Upstox],
             "fetched_ist": iso}.
    """
    live = _live_prices()
    return {
        "prices": live,
        "live_keys": list(live.keys()),
        "fetched_ist": datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(),
    }


def analyze(name: str, price: float, piv: dict) -> dict:
    """Bias, zone, nearest S/R and analyst narrative for a price against pivots."""
    support, resistance = _nearest(_ladder(piv), price)
    if price > piv["R3"]:
        zone = "breakout"
    elif price < piv["S3"]:
        zone = "breakdown"
    else:
        zone = "in-range"
    return {
        "zone": zone,
        "bias": "bullish" if price > piv["P"] else ("bearish" if price < piv["P"] else "neutral"),
        "nearest_support": (support[0], round(support[1])) if support else None,
        "nearest_resistance": (resistance[0], round(resistance[1])) if resistance else None,
        "analyst": _analyst_view(name, price, piv),
    }


def get_index_levels() -> dict:
    """
    Convenience: full levels + analysis in one call (composes the split parts).
    The UI uses get_pivot_bases()/get_live_prices() separately so each caches at
    its own cadence; this stays for direct/programmatic use.
    """
    bases = get_pivot_bases()
    live = get_live_prices()["prices"]
    out = []
    for b in bases["indices"]:
        price = live.get(b["key"]) or b["yf_last"]
        a = analyze(b["name"], price, b["_piv"])
        out.append({
            "name": b["name"], "price": round(price, 2), "live": b["key"] in live,
            "pivot": b["pivot"], "resistances": b["resistances"], "supports": b["supports"],
            "session_date": b["session_date"], **a,
        })
    return {"indices": out, "generated_ist": datetime.now(ZoneInfo("Asia/Kolkata")).isoformat()}


__all__ = ["get_index_levels", "get_pivot_bases", "get_live_prices", "analyze", "INDICES"]
