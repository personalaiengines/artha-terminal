"""
ARTHA Terminal - UDF datafeed for TradingView Advanced Charts.

The exact wire contract TradingView's UDF adapter expects
(https://www.tradingview.com/charting-library-docs/latest/connecting_data/UDF/):

    GET /config   -> DatafeedConfiguration
    GET /symbols  -> one LibrarySymbolInfo (single-symbol mode)
    GET /search   -> [SearchSymbolResultItem]
    GET /history  -> {"s":"ok","t":[],"o":[],"h":[],"l":[],"c":[],"v":[]}
                  or {"s":"no_data","nextTime":<unix>}
                  or {"s":"error","errmsg":"..."}
    GET /time     -> a BARE Unix-seconds integer, not JSON

Two rules this module exists to keep:

* T10 - nothing is fabricated. Every number served comes out of SQLite. A range
  with no bars answers `no_data` (plus `nextTime`, so the widget skips the gap
  instead of re-polling it) - never `{"s":"ok","t":[]}` and never an
  interpolated or forward-filled bar.
* T12 - no secret, token or account identifier is served. No handler here reads
  config, credentials or an account id; the datafeed is market data only.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

from db import get_connection
from services import intraday

# The three F&O indices are not instruments in symbol_master, so they are named
# here. Everything else resolves through symbol_master.
INDEXES = {"NIFTY": ("NIFTY 50", "NSE"),
           "BANKNIFTY": ("NIFTY BANK", "NSE"),
           "SENSEX": ("SENSEX", "BSE")}

SUPPORTED = ["1", "5", "15", "60", "1D"]
_MINUTES = {"1": 1, "5": 5, "15": 15, "60": 60}
_DAILY = {"D", "1D"}

# _candles() returns the most recent N rows, so a range query has to ask for
# enough rows to reach back to `from`. Capped: 5000 trading days is ~20 years,
# well past the 5Y the store holds.
_MAX_DAILY_ROWS = 5000
# Intraday sessions are 375 of the day's 1440 minutes, so a countback of N bars
# spans up to ~4x N bar-widths of wall-clock once nights and weekends are in.
_COUNTBACK_SLACK = 4


def _run(fn, *a):
    """Blocking DB work off the event loop, on the API's shared pool.

    Imported lazily on purpose: api.server imports this module, so a top-level
    import would be circular."""
    from api.server import run
    return run(fn, *a)


def _ticker(raw: str) -> str:
    """"NSE:NIFTY" / "nifty" -> "NIFTY". The widget round-trips whatever
    `full_name` we hand it, so both forms arrive here."""
    return (raw or "").strip().upper().split(":")[-1]


def _lookup(symbol: str) -> dict | None:
    """Resolve a ticker to {symbol, description, exchange, type}, or None."""
    s = _ticker(symbol)
    if s in INDEXES:
        desc, exch = INDEXES[s]
        return {"symbol": s, "description": desc, "exchange": exch, "type": "index"}
    with get_connection() as conn:
        r = conn.execute(
            "SELECT symbol, company_name, exchange FROM symbol_master WHERE symbol = ?",
            (s,)).fetchone()
    if not r:
        return None
    return {"symbol": r["symbol"], "description": r["company_name"] or r["symbol"],
            "exchange": r["exchange"] or "NSE", "type": "stock"}


# ----------------------------------------------------------------------
# /config, /symbols, /search
# ----------------------------------------------------------------------
async def config(req):
    return JSONResponse({
        "supported_resolutions": SUPPORTED,
        "supports_search": True,
        "supports_group_request": False,
        # Deliberate: `crossed`/BROKEN state is already visible in the ladder,
        # the zone rectangle and the `state` string. A fourth channel is
        # decoration, and declaring false is the honest answer.
        "supports_marks": False,
        "supports_timescale_marks": False,
        "supports_time": True,
        "exchanges": [
            {"value": "", "name": "All Exchanges", "desc": ""},
            {"value": "NSE", "name": "NSE", "desc": "National Stock Exchange"},
            {"value": "BSE", "name": "BSE", "desc": "Bombay Stock Exchange"},
        ],
        "symbols_types": [
            {"name": "All types", "value": ""},
            {"name": "Index", "value": "index"},
            {"name": "Stock", "value": "stock"},
        ],
    })


async def symbols(req):
    info = await _run(_lookup, req.query_params.get("symbol") or "")
    if not info:
        return JSONResponse({"s": "error", "errmsg": "unknown symbol"})
    # Only the three indices have an intraday store today. Saying has_intraday
    # for an equity would make the widget request minute bars we do not have.
    intra = info["symbol"] in intraday.SYMBOLS
    return JSONResponse({
        "name": info["symbol"],
        "ticker": info["symbol"],
        "full_name": f'{info["exchange"]}:{info["symbol"]}',
        "description": info["description"],
        "type": info["type"],
        "session": "0915-1530",
        "timezone": "Asia/Kolkata",
        "exchange": info["exchange"],
        "listed_exchange": info["exchange"],
        "currency_code": "INR",
        "minmov": 1,
        "pricescale": 100,
        "has_intraday": intra,
        "has_daily": True,
        "supported_resolutions": SUPPORTED if intra else ["1D"],
        "intraday_multipliers": ["1", "5", "15", "60"] if intra else [],
        "volume_precision": 0,
        # False so the widget leaves gaps as gaps instead of drawing a flat
        # placeholder candle where no trade happened (T10).
        "has_empty_bars": False,
        "data_status": "endofday",
    })


def _search(query: str, limit: int) -> list[dict]:
    q = _ticker(query)
    out = [{"symbol": s, "full_name": f"{exch}:{s}", "description": desc,
            "exchange": exch, "ticker": s, "type": "index"}
           for s, (desc, exch) in INDEXES.items()
           if not q or q in s or q in desc]
    room = limit - len(out)
    if room > 0:
        like = f"%{q}%"
        with get_connection() as conn:
            # Exact ticker, then prefix, then biggest company. `mcap_rank` is
            # NULL for all 5173 rows (nothing populates it), so ordering by it
            # degenerates to alphabetical — typing "REL" returned ABREL,
            # GILT5YBEES and LORENZINI APPARELS while RELIANCE never appeared.
            # market_cap_cr IS populated.
            rows = conn.execute(
                "SELECT symbol, company_name, exchange FROM symbol_master "
                "WHERE symbol LIKE ? OR company_name LIKE ? "
                "ORDER BY (symbol = ?) DESC, (symbol LIKE ?) DESC, "
                "         market_cap_cr IS NULL, market_cap_cr DESC, symbol "
                "LIMIT ?",
                (like, like, q, f"{q}%", room)).fetchall()
        out += [{"symbol": r["symbol"], "full_name": f'{r["exchange"] or "NSE"}:{r["symbol"]}',
                 "description": r["company_name"] or r["symbol"],
                 "exchange": r["exchange"] or "NSE", "ticker": r["symbol"], "type": "stock"}
                for r in rows]
    return out[:limit]


async def search(req):
    try:
        limit = min(50, max(1, int(req.query_params.get("limit") or 30)))
    except ValueError:
        limit = 30
    return JSONResponse(await _run(_search, req.query_params.get("query") or "", limit))


# ----------------------------------------------------------------------
# /history
# ----------------------------------------------------------------------
def _day_epoch(date_str: str) -> int | None:
    """"YYYY-MM-DD" -> Unix seconds at 00:00 UTC, UDF's daily-bar convention."""
    try:
        return int(datetime.strptime(date_str, "%Y-%m-%d")
                   .replace(tzinfo=timezone.utc).timestamp())
    except (TypeError, ValueError):
        return None


def _daily(symbol: str, frm: int, to: int, countback: int | None) -> tuple[list[dict], int | None]:
    """(bars in range, nextTime) from prices_daily via api.server._candles()."""
    from api.server import _candles

    span_days = (int(time.time()) - frm) // 86400 + 10
    rows = _candles(symbol, max(2, min(_MAX_DAILY_ROWS, span_days)))
    bars = []
    for r in rows:
        ts = _day_epoch(r["t"])
        if ts is None or ts > to:
            continue
        bars.append({"t": ts, "open": r["open"], "high": r["high"], "low": r["low"],
                     "close": r["close"], "volume": r["volume"]})
    bars = bars[-countback:] if countback else [b for b in bars if b["t"] >= frm]
    if bars:
        return bars, None

    # Nothing in range - point the widget at the nearest real bar we do have.
    with get_connection() as conn:
        nxt = conn.execute(
            "SELECT min(date) FROM prices_daily WHERE symbol = ? AND date > ?",
            (symbol, _iso(to))).fetchone()[0]
        if nxt is None:
            nxt = conn.execute(
                "SELECT max(date) FROM prices_daily WHERE symbol = ? AND date < ?",
                (symbol, _iso(frm))).fetchone()[0]
    return [], _day_epoch(nxt) if nxt else None


def _iso(ts: int) -> str:
    return datetime.fromtimestamp(max(0, ts), timezone.utc).strftime("%Y-%m-%d")


def _intraday(symbol: str, minutes: int, frm: int, to: int,
              countback: int | None) -> tuple[list[dict], int | None]:
    """(bars in range, nextTime) from the 1-minute store, resampled."""
    if countback:
        frm = min(frm, to - countback * minutes * 60 * _COUNTBACK_SLACK)
    bars = intraday.read(symbol, minutes, frm, to)
    if countback:
        bars = bars[-countback:]
    if bars:
        return bars, None
    return [], intraday.neighbour_ts(symbol, frm, to)


async def history(req):
    q = req.query_params
    sym = _ticker(q.get("symbol") or "")
    res = (q.get("resolution") or "1D").strip().upper()
    try:
        # TradingView sends these as integers, but a float slips through some
        # library versions. Anything else is a client bug, not a server one.
        frm = int(float(q.get("from") or 0))
        to = int(float(q.get("to") or time.time()))
        countback = int(q.get("countback")) if q.get("countback") else None
    except (TypeError, ValueError):
        return JSONResponse({"s": "error", "errmsg": "invalid range"})
    if to < frm or (countback is not None and countback <= 0):
        return JSONResponse({"s": "error", "errmsg": "invalid range"})

    if res not in _DAILY and res not in _MINUTES:
        return JSONResponse({"s": "error", "errmsg": "unsupported resolution"})

    info = await _run(_lookup, sym)
    if not info:
        return JSONResponse({"s": "error", "errmsg": "unknown symbol"})
    sym = info["symbol"]

    if res in _DAILY:
        bars, nxt = await _run(_daily, sym, frm, to, countback)
    elif sym not in intraday.SYMBOLS:
        # has_intraday:false already said so; answering no_data is the honest
        # echo, not an error and certainly not a synthesised series.
        bars, nxt = [], None
    else:
        bars, nxt = await _run(_intraday, sym, _MINUTES[res], frm, to, countback)

    if not bars:
        return JSONResponse({"s": "no_data", **({"nextTime": nxt} if nxt else {})})

    return JSONResponse({
        "s": "ok",
        "t": [b["t"] for b in bars],
        "o": [b["open"] for b in bars],
        "h": [b["high"] for b in bars],
        "l": [b["low"] for b in bars],
        "c": [b["close"] for b in bars],
        "v": [b["volume"] for b in bars],
    })


async def server_time(req):
    """A BARE integer. Wrapping it in JSON breaks the widget's clock sync."""
    return PlainTextResponse(str(int(time.time())))


routes = [
    Route("/api/udf/config", config),
    Route("/api/udf/symbols", symbols),
    Route("/api/udf/search", search),
    Route("/api/udf/history", history),
    Route("/api/udf/time", server_time),
]
