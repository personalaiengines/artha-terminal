"""
ARTHA Terminal - intraday bar store + resampler.

Upstox serves 1-minute candles for roughly the trailing month (verified live:
~8250 bars over a 30-day window, 0 bars at 60 days) and hard-rejects the coarser
intraday intervals - a direct call to /v2/historical-candle/{key}/5minute/... is
HTTP 400 UDAPI1020 "Interval accepts one of (1minute,30minute,day,week,month)".

So 5m/15m/1h cannot be fetched at all. They are RESAMPLED here from the stored
1-minute bars: open=first, high=max, low=min, close=last, volume=sum. A bucket
with no source bars emits NO bar - a hole in the market data stays a hole, it is
never interpolated or forward-filled. The trailing bucket of a live session is
flagged `partial` so a forming bar is never read as a settled one.

Fetching itself is not reimplemented: services.fno_service already has the paged
historical wrapper and the today-only intraday wrapper.
"""

from __future__ import annotations

import time
from datetime import datetime

from db import get_connection

# UDF ticker -> services.fno_service index key. Indices only: the F&O page charts
# exactly these three, and get_index_history is keyed on FNO_UNDERLYINGS.
# Widening to equities is adding keys here plus an equity fetch wrapper, not a
# redesign of the store.
SYMBOLS = {"NIFTY": "nifty50", "BANKNIFTY": "banknifty", "SENSEX": "sensex"}

RESOLUTIONS = (1, 5, 15, 60)

# The regular session opens 09:15 IST = 03:45 UTC = 13500s past UTC midnight.
# Buckets are anchored to THAT, not to the UTC hour, so a 60-minute bar runs
# 09:15-10:15 like the exchange session instead of 09:00-10:00 (which would put
# the first bar of every day 45 minutes before the market opened).
_SESSION_OPEN = 13500
_DAY = 86400

# One refill attempt per symbol per 5 minutes. Bounds the Upstox traffic when a
# chart is polling and the store is legitimately behind (e.g. after the close,
# when `last` is always older than `now`).
# ponytail: process-local throttle, resets on restart. Fine for a single API
# container; move to a DB column if this ever runs multi-process.
_FILL_THROTTLE = 300
_last_fill: dict[str, float] = {}


def _epoch(ts: str) -> int | None:
    """Upstox ISO timestamp ("2026-07-31T09:15:00+05:30") -> Unix seconds, UTC.

    The +05:30 offset is part of the string and datetime.fromisoformat honours
    it. Parsing it as naive local time would shift every bar by 5h30m."""
    try:
        return int(datetime.fromisoformat(ts).timestamp())
    except (TypeError, ValueError):
        return None


def _bucket(ts: int, step: int) -> int:
    """Bucket open time for `ts`, anchored to the session open (see _SESSION_OPEN).

    Session bars fall between 03:45 and 10:00 UTC, so the IST trading date and
    the UTC date always agree here - no timezone round-trip needed."""
    open_ = ts - (ts % _DAY) + _SESSION_OPEN
    return open_ + (ts - open_) // step * step


def resample(bars: list[dict], minutes: int, now: int | None = None) -> list[dict]:
    """1-minute bars -> `minutes`-minute bars. `bars` must be ascending by "t".

    open=first, high=max, low=min, close=last, volume=sum. Buckets with no
    source bars are simply absent from the output (T10). `n` is how many
    1-minute bars actually went into each bar, and `partial` marks a bucket
    whose window has not elapsed yet (T9)."""
    step = minutes * 60
    now = int(time.time()) if now is None else int(now)
    out: list[dict] = []
    for b in bars:
        k = _bucket(int(b["t"]), step)
        if out and out[-1]["t"] == k:
            cur = out[-1]
            cur["high"] = max(cur["high"], b["high"])
            cur["low"] = min(cur["low"], b["low"])
            cur["close"] = b["close"]
            cur["volume"] += b["volume"]
            cur["n"] += 1
        else:
            out.append({"t": k, "open": b["open"], "high": b["high"], "low": b["low"],
                        "close": b["close"], "volume": b["volume"], "n": 1,
                        "partial": False})
    if out and out[-1]["t"] + step > now:
        out[-1]["partial"] = True
    return out


def fill(symbol: str, days: int = 30, db_path=None) -> int:
    """Fetch 1-minute bars for one index and store them; returns rows written.

    History comes from the paged historical endpoint and today's forming session
    from the intraday one (the historical endpoint does not return it). Both
    wrappers already return [] on any failure, and a failed fetch stores nothing
    and returns 0 - never a placeholder bar."""
    symbol = symbol.upper()
    index = SYMBOLS.get(symbol)
    if not index:
        return 0

    from services.fno_service import get_index_history, get_index_intraday

    _last_fill[symbol] = time.time()   # set before the call: a failure throttles too
    rows = list(get_index_history(index, "1minute", days))
    rows += list(get_index_intraday(index, "1minute"))

    out = []
    for r in rows:
        # Upstox row: [iso_ts, open, high, low, close, volume, oi]
        if not r or len(r) < 6:
            continue
        ts = _epoch(r[0])
        if ts is None or any(v is None for v in r[1:5]):
            continue
        out.append((symbol, ts, float(r[1]), float(r[2]), float(r[3]), float(r[4]),
                    int(r[5] or 0)))
    if not out:
        return 0
    with get_connection(db_path) as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO prices_intraday "
            "(symbol, ts, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
            out)
    return len(out)


def coverage(symbol: str, db_path=None) -> dict:
    """What the store actually holds for `symbol` - the honest-coverage source
    for "this chart shows N bars from X to Y" (T9). None/0 when empty."""
    with get_connection(db_path) as conn:
        r = conn.execute(
            "SELECT count(*) AS n, min(ts) AS f, max(ts) AS l "
            "FROM prices_intraday WHERE symbol = ?", (symbol.upper(),)).fetchone()
    return {"bars": r["n"] or 0, "first": r["f"], "last": r["l"]}


def read(symbol: str, minutes: int = 1, frm: int = 0, to: int | None = None,
         db_path=None) -> list[dict]:
    """Stored bars in [frm, to] at `minutes` resolution, oldest first.

    Lazily fills from Upstox when the store cannot already answer the window.
    ponytail: lazy fill on read - add an ingestion/scheduler.py JOBS entry only
    if the store must grow past Upstox's ~30-day 1-minute ceiling unattended."""
    symbol = symbol.upper()
    if symbol not in SYMBOLS or minutes not in RESOLUTIONS:
        return []
    now = time.time()
    to = int(now) if to is None else int(to)
    frm = int(frm)

    cov = coverage(symbol, db_path)
    stale = (not cov["bars"] or cov["last"] < min(to, int(now)) - 60
             or cov["first"] > frm)
    if stale and now - _last_fill.get(symbol, 0.0) > _FILL_THROTTLE:
        fill(symbol, db_path=db_path)

    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT ts, open, high, low, close, volume FROM prices_intraday "
            "WHERE symbol = ? AND ts >= ? AND ts <= ? ORDER BY ts",
            (symbol, frm, to)).fetchall()
    bars = [{"t": r["ts"], "open": r["open"], "high": r["high"], "low": r["low"],
             "close": r["close"], "volume": r["volume"] or 0} for r in rows]
    return resample(bars, minutes, now=int(now))


def neighbour_ts(symbol: str, frm: int, to: int, db_path=None) -> int | None:
    """Nearest stored bar OUTSIDE [frm, to] - the first one after `to`, else the
    last one before `frm`. This is UDF /history's `nextTime`: it tells the widget
    where data resumes so it stops re-polling an empty gap."""
    symbol = symbol.upper()
    with get_connection(db_path) as conn:
        r = conn.execute(
            "SELECT min(ts) FROM prices_intraday WHERE symbol = ? AND ts > ?",
            (symbol, int(to))).fetchone()[0]
        if r is None:
            r = conn.execute(
                "SELECT max(ts) FROM prices_intraday WHERE symbol = ? AND ts < ?",
                (symbol, int(frm))).fetchone()[0]
    return int(r) if r is not None else None


__all__ = ["SYMBOLS", "RESOLUTIONS", "resample", "fill", "read", "coverage",
           "neighbour_ts"]
