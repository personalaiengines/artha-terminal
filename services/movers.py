"""
ARTHA Terminal - Market-wide Top Gainers / Losers

Why this exists:
    The old page ranked movers over only the ~20 symbols in the local price DB,
    so its "top gainer" was meaningless vs the official NSE list (e.g. it showed
    WIPRO when the real market top gainer was FEDERALBNK). This service ranks over
    a broad universe so the result matches what traders actually see.

Sources, in order of preference:
    1. NSE  live-analysis-variations  — authoritative, market-wide, exactly what
       the official Top Gainers/Losers page shows. NSE is cookie-gated and often
       blocks server IPs, so we try ONCE with a short timeout and move on.
    2. yfinance batch over the NIFTY-100 + liquid mid-cap universe — computed from
       the last two closes. Reliable from the container, close to the NSE list.

Returns real numbers only; nothing is mocked.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


# ------------------------------------------------------------------
# 1. NSE authoritative (best-effort, single short attempt)
# ------------------------------------------------------------------

def _from_nse(top_n: int) -> dict | None:
    import httpx

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/market-data/top-gainers-losers",
    }

    def _fetch(index_kind: str):
        try:
            with httpx.Client(headers=headers, timeout=8.0, follow_redirects=True) as c:
                c.get("https://www.nseindia.com")
                c.get("https://www.nseindia.com/market-data/top-gainers-losers")
                r = c.get(f"https://www.nseindia.com/api/live-analysis-variations?index={index_kind}")
                if r.status_code == 200:
                    return r.json()
        except Exception:
            return None
        return None

    def _rows(payload) -> list[dict]:
        if not isinstance(payload, dict):
            return []
        # Prefer the broadest group NSE returns (NIFTY / allSec / FOSec).
        for key in ("NIFTY", "allSec", "FOSec", "SecGtr20"):
            grp = payload.get(key)
            if isinstance(grp, dict) and grp.get("data"):
                out = []
                for row in grp["data"]:
                    sym = row.get("symbol")
                    pct = row.get("perChange")
                    if pct is None:
                        pct = row.get("net_price")
                    ltp = row.get("ltp") or row.get("lastPrice")
                    if sym and pct is not None:
                        try:
                            out.append({"symbol": sym, "pct": float(pct),
                                        "price": float(ltp) if ltp is not None else None})
                        except Exception:
                            continue
                if out:
                    return out
        return []

    g = _rows(_fetch("gainers"))
    l = _rows(_fetch("loosers"))  # NSE's own (mis)spelling
    if not g and not l:
        return None
    g.sort(key=lambda x: x["pct"], reverse=True)
    l.sort(key=lambda x: x["pct"])
    return {"gainers": g[:top_n], "losers": l[:top_n], "source": "NSE (market-wide)"}


# ------------------------------------------------------------------
# 2. yfinance over the broad universe (reliable fallback)
# ------------------------------------------------------------------

def _from_yfinance(top_n: int) -> dict | None:
    import warnings, logging
    warnings.filterwarnings("ignore")
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    import yfinance as yf
    from services.nifty50 import broad_universe

    syms = broad_universe()
    tickers = [f"{s}.NS" for s in syms]
    try:
        df = yf.download(tickers, period="5d", interval="1d", progress=False,
                         group_by="ticker", threads=True)
    except Exception:
        return None
    if df is None or len(df) == 0:
        return None

    moves: list[dict] = []
    volume: list[dict] = []
    for s in syms:
        try:
            sub = df[f"{s}.NS"]
            closes = sub["Close"].dropna()
            if len(closes) >= 2 and closes.iloc[-2]:
                pct = (closes.iloc[-1] / closes.iloc[-2] - 1) * 100
                last = round(float(closes.iloc[-1]), 2)
                moves.append({"symbol": s, "pct": round(float(pct), 2), "price": last})
                # Latest-session traded volume (shares) + value traded (₹).
                try:
                    vol = float(sub["Volume"].dropna().iloc[-1])
                    if vol > 0:
                        volume.append({
                            "symbol": s, "volume": int(vol), "price": last,
                            "pct": round(float(pct), 2),
                            "value_cr": round(vol * last / 1e7, 1),  # ₹ crore
                        })
                except Exception:
                    pass
        except Exception:
            continue
    if not moves:
        return None
    moves.sort(key=lambda x: x["pct"], reverse=True)
    volume.sort(key=lambda x: x["volume"], reverse=True)
    return {
        "gainers": moves[:top_n],
        "losers": sorted(moves, key=lambda x: x["pct"])[:top_n],
        "volume": volume[:top_n],
        "source": f"yfinance · NIFTY-100+ universe ({len(moves)} stocks)",
    }


# ------------------------------------------------------------------
# Public
# ------------------------------------------------------------------

def get_top_movers(top_n: int = 10) -> dict:
    """
    Market-wide top gainers, losers, and volume leaders.

    yfinance gives all three from one batch (movers + volume). NSE, when reachable,
    is authoritative for gainers/losers and overrides those two; volume leaders
    always come from the yfinance pass.

    Returns:
        {"gainers": [{symbol, pct, price}], "losers": [...],
         "volume": [{symbol, volume, price, pct, value_cr}],
         "source": str, "generated_ist": iso, "ok": bool}
    """
    yf_result = _from_yfinance(top_n)
    nse = _from_nse(top_n)

    if nse and yf_result:
        result = {
            "gainers": nse["gainers"], "losers": nse["losers"],
            "volume": yf_result.get("volume", []),
            "source": nse["source"] + " · volume via yfinance",
        }
    else:
        result = nse or yf_result

    if not result:
        return {"gainers": [], "losers": [], "volume": [], "source": None, "ok": False,
                "generated_ist": datetime.now(ZoneInfo("Asia/Kolkata")).isoformat()}

    result.setdefault("volume", [])
    result["ok"] = True
    result["generated_ist"] = datetime.now(ZoneInfo("Asia/Kolkata")).isoformat()
    return result


__all__ = ["get_top_movers"]
