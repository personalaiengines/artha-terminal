"""
ARTHA Terminal - Institutional Flows (FII/DII) service

Real data:
  • Daily FII/FPI and DII net cash-market buy/sell — NSE fiidiiTradeReact.
    This is the authoritative aggregate figure, published once per day after
    market close. We persist each reading to build a multi-day trend.

AI layer (clearly labelled, sourced):
  • "Flow intelligence" — where FIIs/DIIs are reportedly buying/selling by
    sector/stock. This granularity is NOT published as official daily data
    (only quarterly shareholding is), so it is summarised by an NVIDIA NIM model
    from live news search, with a source link on every claim. It is market
    commentary, NOT official flow numbers.
"""

from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from db import get_connection


_NSE_FIIDII = "https://www.nseindia.com/api/fiidiiTradeReact"


# ------------------------------------------------------------------
# Real FII/DII fetch (NSE) + persistence
# ------------------------------------------------------------------

def _to_float(v) -> float | None:
    try:
        return float(str(v).replace(",", "").strip())
    except Exception:
        return None


def fetch_fii_dii() -> dict:
    """
    Latest FII/FPI and DII net cash figures from NSE.

    Returns {"fii": {buy, sell, net}, "dii": {buy, sell, net}, "date": "DD-Mon-YYYY"}
    or {} on failure. Persists the reading for trend building.
    """
    import httpx
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/reports/fii-dii",
    }
    rows = None
    # NSE is flaky and cookie-gated — retry a couple of times with a fresh session.
    for _ in range(3):
        try:
            with httpx.Client(headers=headers, timeout=15.0, follow_redirects=True) as c:
                # Best-effort cookie seeding; these endpoints intermittently 403 or
                # hang, but their failure must NOT abort the actual API call below.
                for warm in ("https://www.nseindia.com",
                             "https://www.nseindia.com/reports/fii-dii"):
                    try:
                        c.get(warm)
                    except Exception:
                        pass
                r = c.get(_NSE_FIIDII)
                if r.status_code == 200:
                    rows = r.json()
                    break
        except Exception:
            continue
    if rows is None:
        return {}

    out = {"fii": None, "dii": None, "date": None}
    for row in rows if isinstance(rows, list) else []:
        cat = (row.get("category") or "").upper()
        rec = {
            "buy": _to_float(row.get("buyValue")),
            "sell": _to_float(row.get("sellValue")),
            "net": _to_float(row.get("netValue")),
        }
        out["date"] = row.get("date") or out["date"]
        if "FII" in cat or "FPI" in cat:
            out["fii"] = rec
        elif "DII" in cat:
            out["dii"] = rec

    if out["fii"] and out["dii"] and out["date"]:
        _persist(out)
        return out
    return {}


def _persist(data: dict) -> None:
    """Upsert a daily FII/DII reading for trend building."""
    try:
        d = datetime.strptime(data["date"], "%d-%b-%Y").date().isoformat()
    except Exception:
        return
    try:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO fii_dii_flows (date, fii_net, dii_net, fii_buy, fii_sell, dii_buy, dii_sell)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    fii_net=excluded.fii_net, dii_net=excluded.dii_net,
                    fii_buy=excluded.fii_buy, fii_sell=excluded.fii_sell,
                    dii_buy=excluded.dii_buy, dii_sell=excluded.dii_sell
                """,
                (d, data["fii"]["net"], data["dii"]["net"],
                 data["fii"]["buy"], data["fii"]["sell"],
                 data["dii"]["buy"], data["dii"]["sell"]),
            )
            conn.commit()
    except Exception:
        pass


def get_flow_trend(days: int = 10) -> dict:
    """
    FII/DII net-flow trend from stored readings.

    Returns {"series": [{date, fii_net, dii_net}], "fii_streak": int,
             "dii_streak": int, "fii_sum": float, "dii_sum": float}.
    Streak = consecutive most-recent days of net buying (+) or selling (-).
    """
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT date, fii_net, dii_net FROM fii_dii_flows ORDER BY date DESC LIMIT ?",
                (days,),
            )
            rows = [dict(r) for r in cur.fetchall()]
    except Exception:
        rows = []

    rows.reverse()  # oldest -> newest

    def _streak(vals):
        if not vals:
            return 0
        sign = 1 if vals[-1] >= 0 else -1
        n = 0
        for v in reversed(vals):
            if (v >= 0 and sign > 0) or (v < 0 and sign < 0):
                n += 1
            else:
                break
        return n * sign

    fii = [r["fii_net"] for r in rows]
    dii = [r["dii_net"] for r in rows]
    return {
        "series": rows,
        "fii_streak": _streak(fii),
        "dii_streak": _streak(dii),
        "fii_sum": round(sum(fii), 2),
        "dii_sum": round(sum(dii), 2),
    }


def _stance(net: float | None) -> tuple[str, str]:
    """(label, key) bullish/bearish/neutral from a net figure."""
    if net is None:
        return ("—", "neutral")
    if net > 0:
        return ("🟢 Net Buying", "bullish")
    if net < 0:
        return ("🔴 Net Selling", "bearish")
    return ("⚪ Flat", "neutral")


def _latest_stored() -> dict:
    """Most recent stored FII/DII reading (fallback when live NSE fetch fails)."""
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT date, fii_net, dii_net, fii_buy, fii_sell, dii_buy, dii_sell "
                "FROM fii_dii_flows ORDER BY date DESC LIMIT 1"
            )
            r = cur.fetchone()
    except Exception:
        r = None
    if not r:
        return {}
    try:
        disp_date = datetime.fromisoformat(r["date"]).strftime("%d-%b-%Y")
    except Exception:
        disp_date = r["date"]
    return {
        "date": disp_date,
        "fii": {"buy": r["fii_buy"], "sell": r["fii_sell"], "net": r["fii_net"]},
        "dii": {"buy": r["dii_buy"], "sell": r["dii_sell"], "net": r["dii_net"]},
        "stale": True,
    }


def get_institutional_snapshot() -> dict:
    """Combined FII/DII snapshot: today's flows, stances, and stored trend.

    Falls back to the most recent stored reading if the live NSE fetch fails, so
    the panel keeps showing the last known figures instead of 'unavailable'.
    """
    today = fetch_fii_dii()
    if not (today.get("fii") and today.get("dii")):
        today = _latest_stored()
    trend = get_flow_trend()

    fii_net = today.get("fii", {}).get("net") if today.get("fii") else None
    dii_net = today.get("dii", {}).get("net") if today.get("dii") else None
    fii_label, fii_key = _stance(fii_net)
    dii_label, dii_key = _stance(dii_net)

    return {
        "date": today.get("date"),
        "fii": today.get("fii"),
        "dii": today.get("dii"),
        "fii_stance": fii_label, "fii_key": fii_key,
        "dii_stance": dii_label, "dii_key": dii_key,
        "stale": today.get("stale", False),
        "trend": trend,
        "generated_ist": datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(),
    }


# ------------------------------------------------------------------
# AI Flow Intelligence (news-derived, sourced, labelled)
# ------------------------------------------------------------------

def get_flow_intelligence() -> dict:
    """
    Where FIIs/DIIs are reportedly active by sector/stock — summarised by NIM
    from live news search, WITH source links. Not official flow data.

    Returns {"items": [{who, direction, target, note, source_url}], "ok": bool}.
    """
    from services.market_events import _search_sync, _nim_extract  # reuse helpers

    fii_res = _search_sync("FII foreign investors buying selling Indian stocks sectors this week")
    dii_res = _search_sync("DII domestic institutional investors buying Indian sectors stocks this week")
    results = (fii_res or []) + (dii_res or [])
    if not results:
        return {"items": [], "ok": False}

    snippets = "\n".join(
        f"- {r.get('title','')} | {r.get('link','')} | {r.get('snippet','')}"
        for r in results[:10]
    )
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
    prompt = (
        f"Today is {today}. From the news search results below, extract concrete claims "
        f"about where FIIs (foreign) or DIIs (domestic) are BUYING or SELLING in Indian "
        f"markets — by sector or specific stock. Use ONLY what the results state.\n\n"
        f"{snippets}\n\n"
        f'Return ONLY a JSON array; each item: {{"who":"FII"|"DII","direction":"buying"|'
        f'"selling","target":"<sector or stock>","note":"<short context>","source_url":'
        f'"<a link from above>"}}. Max 10. No preamble.'
    )
    import json

    def _parse(raw: str) -> list[dict]:
        if not raw:
            return []
        parsed = []
        m = re.search(r"\[.*\]", raw, re.DOTALL)
        if m:
            try:
                parsed = json.loads(m.group(0))
            except Exception:
                parsed = []
        if not parsed:
            for b in re.findall(r"\{[^{}]*\}", raw, re.DOTALL):
                try:
                    parsed.append(json.loads(b))
                except Exception:
                    continue
        out = []
        for it in parsed if isinstance(parsed, list) else []:
            if not isinstance(it, dict):
                continue
            who = str(it.get("who", "")).upper()
            direction = str(it.get("direction", "")).lower()
            target = str(it.get("target", "")).strip()
            url = str(it.get("source_url", "")).strip()
            if who in ("FII", "DII") and direction in ("buying", "selling") and target and url.startswith("http"):
                out.append({
                    "who": who, "direction": direction, "target": target,
                    "note": str(it.get("note", "")).strip()[:90], "source_url": url,
                })
        return out

    # NIM free tier is variable — retry the cheap extraction a few times.
    items = []
    for _ in range(3):
        items = _parse(_nim_extract(prompt, timeout=45.0))
        if items:
            break
    return {"items": items[:10], "ok": bool(items)}


__all__ = ["fetch_fii_dii", "get_flow_trend", "get_institutional_snapshot",
           "get_flow_intelligence"]
