"""
ARTHA Terminal - Market Pulse service
Real market internals for the landing hero: headline indices, market breadth
(advances/declines), sector breadth, and an AI "strategist's read".

Division of labour (important):
  • Upstox / DB provide the raw data.
  • Deterministic MATH computes breadth and sector stats — never the LLM, which
    is unreliable at arithmetic over many numbers.
  • The LLM (NVIDIA NIM) only INTERPRETS the finished numbers into a short
    senior-strategist commentary. It is grounded on real figures and cannot
    invent them.

Breadth is computed from the tracked large-cap universe (symbol_master), using
the last two daily closes in prices_daily, so it works 24/7. During market hours
this reflects the most recent completed session; a live intraday overlay can be
layered on later.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from agent.prompts import COMPLIANCE, GROUNDING, HOUSE_STYLE
from db import get_connection

# The two-sentence bound is this surface's own — HOUSE_STYLE keys length to
# scope, and the pulse strapline's scope is two sentences.
_SYSTEM = (
    f"{GROUNDING}\n\n{HOUSE_STYLE}\n\n{COMPLIANCE}\n\n"
    "You are a senior Indian equity market strategist. In EXACTLY two crisp "
    "sentences, interpret today's market internals — whether the move is broad "
    "or narrow, any sector rotation, and the risk tone. Plain prose: no "
    "headings, no bullets, no disclaimer line."
)


# ------------------------------------------------------------------
# Headline indices (live)
# ------------------------------------------------------------------

def _live_indices() -> dict:
    """Nifty 50 / Sensex / Bank Nifty live values + % change from Upstox."""
    import asyncio
    from services.upstox import UpstoxClient

    async def _go():
        return await UpstoxClient().get_index_quotes(["nifty50", "sensex", "banknifty"])

    try:
        loop = asyncio.new_event_loop()
        try:
            q = loop.run_until_complete(_go())
        finally:
            loop.close()
    except Exception:
        return {}
    if not isinstance(q, dict) or "error" in q:
        return {}
    return q


# ------------------------------------------------------------------
# Breadth + sector stats (deterministic math on real data)
# ------------------------------------------------------------------

def _nifty50_changes() -> list[dict]:
    """
    Per-stock day change for the NIFTY 50 via a single batched yfinance download
    (live-ish, ~15 min delayed, works during and outside market hours).

    Returns [] on failure so the caller can fall back to the DB universe.
    """
    import logging
    from services.constituents import nifty50_sectors
    sectors = nifty50_sectors()
    try:
        import yfinance as yf
    except Exception:
        return []

    # yfinance logs noisy "possibly delisted" errors to stderr for any ticker it
    # can't price (e.g. LTIM); we drop those gracefully, so silence the noise.
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)

    syms = list(sectors)
    tickers = [f"{s}.NS" for s in syms]
    try:
        df = yf.download(tickers, period="5d", interval="1d", group_by="ticker",
                         progress=False, threads=True)
    except Exception:
        return []
    if df is None or df.empty:
        return []

    out = []
    for s in syms:
        try:
            closes = df[f"{s}.NS"]["Close"].dropna()
            if len(closes) >= 2:
                chg = (closes.iloc[-1] - closes.iloc[-2]) / closes.iloc[-2] * 100.0
                out.append({"symbol": s, "sector": sectors[s], "chg": round(float(chg), 2)})
        except Exception:
            continue
    return out


def _stock_changes() -> list[dict]:
    """Per-stock day change from the last two closes, joined with sector."""
    sql = """
        WITH ranked AS (
            SELECT symbol, close, date,
                   ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC) rn
            FROM prices_daily
        )
        SELECT r1.symbol AS symbol, m.sector AS sector,
               r1.close AS latest, r2.close AS prev,
               (r1.close - r2.close) / r2.close * 100.0 AS chg
        FROM ranked r1
        JOIN ranked r2 ON r1.symbol = r2.symbol AND r1.rn = 1 AND r2.rn = 2
        LEFT JOIN symbol_master m ON m.symbol = r1.symbol
        WHERE r2.close > 0
    """
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute(sql)
            return [
                {"symbol": r["symbol"], "sector": r["sector"] or "Other",
                 "chg": round(r["chg"], 2)}
                for r in cur.fetchall()
            ]
    except Exception:
        return []


def _sector_changes() -> list[dict]:
    """Per-stock day change for every INDEXED stock, labelled with NSE industry.

    Sector rotation gets its own deterministic source, separate from breadth.
    Breadth flips between a live yfinance NIFTY-50 pass and the whole DB
    universe depending on whether yfinance answered — 50 stocks one refresh,
    3222 the next. Feeding the heatmap from that made every sector's average,
    stock count and even the list of sectors change on each poll.

    This is pure SQL over the last two closes, restricted to index members, so
    the same input always produces the same heatmap. `industry` also matches
    the label the screener filters on, which is what makes the click-through
    from a tile land on a non-empty grid.
    """
    sql = """
        WITH ranked AS (
            SELECT symbol, close, date,
                   ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC) rn
            FROM prices_daily
        ),
        sectors AS (
            SELECT symbol, MIN(industry) AS industry
              FROM index_members WHERE industry IS NOT NULL
             GROUP BY symbol
        )
        SELECT r1.symbol AS symbol, s.industry AS sector,
               (r1.close - r2.close) / r2.close * 100.0 AS chg
        FROM ranked r1
        JOIN ranked r2 ON r1.symbol = r2.symbol AND r1.rn = 1 AND r2.rn = 2
        JOIN sectors s ON s.symbol = r1.symbol
        WHERE r2.close > 0
    """
    try:
        with get_connection() as conn:
            return [{"symbol": r["symbol"], "sector": r["sector"],
                     "chg": round(r["chg"], 2)}
                    for r in conn.execute(sql).fetchall()]
    except Exception:
        return []


def _sector_breadth(changes: list[dict]) -> list[dict]:
    """Average change + advance count per sector, sorted best-first."""
    by_sector: dict[str, list[float]] = {}
    for c in changes:
        by_sector.setdefault(c["sector"], []).append(c["chg"])
    out = []
    for sector, chgs in by_sector.items():
        adv = sum(1 for x in chgs if x > 0)
        out.append({
            "sector": sector,
            "avg_chg": round(sum(chgs) / len(chgs), 2),
            "advancing": adv,
            "total": len(chgs),
        })
    return sorted(out, key=lambda s: s["avg_chg"], reverse=True)


def _mood(breadth_pct: float, indices: dict) -> tuple[str, str]:
    """Market mood tag from breadth + index direction. (emoji_label, key)."""
    idx_up = sum(1 for v in indices.values()
                 if isinstance(v, dict) and (v.get("change") or 0) > 0)
    if breadth_pct >= 60 and idx_up >= 2:
        return ("🔥 Risk-On", "risk-on")
    if breadth_pct <= 40 and idx_up <= 1:
        return ("❄️ Risk-Off", "risk-off")
    return ("⚖️ Mixed", "mixed")


def get_market_pulse() -> dict:
    """
    Assemble the full market-pulse snapshot (all real / computed).

    Returns {indices[], breadth{}, sectors[], leaders[], laggards[],
             top_gainer, top_loser, mood, mood_key, universe, generated_ist}.
    """
    idx_raw = _live_indices()
    order = [("nifty50", "NIFTY 50"), ("sensex", "SENSEX"), ("banknifty", "BANK NIFTY")]
    indices = []
    for key, name in order:
        v = idx_raw.get(key, {})
        indices.append({
            "name": name,
            "value": v.get("value"),
            "change": v.get("change"),
            "live": bool(v.get("value")),
        })

    # Prefer live NIFTY 50 breadth (yfinance); fall back to the DB large-cap set.
    changes = _nifty50_changes()
    universe_label = "NIFTY 50"
    if len(changes) < 30:  # yfinance failed or returned too few — use DB
        changes = _stock_changes()
        universe_label = "tracked large-caps"

    total = len(changes)
    advancing = sum(1 for c in changes if c["chg"] > 0)
    declining = sum(1 for c in changes if c["chg"] < 0)
    pct = round(advancing / total * 100) if total else 0

    # Sector rotation is computed from its own stable universe, NOT from
    # `changes` — that variable is whichever of two very differently sized
    # sources answered this time, so the heatmap it produced was different on
    # every refresh. Falls back to `changes` only if no index membership has
    # been ingested at all.
    sector_rows = _sector_changes() or changes
    sectors = _sector_breadth(sector_rows)
    ranked = sorted(changes, key=lambda c: c["chg"], reverse=True)
    mood_label, mood_key = _mood(pct, idx_raw)

    return {
        "indices": indices,
        "breadth": {"pct": pct, "advancing": advancing,
                    "declining": declining, "total": total},
        "sectors": sectors,
        "leaders": [s for s in sectors if s["avg_chg"] > 0][:3],
        "laggards": [s for s in sectors if s["avg_chg"] < 0][-3:],
        "top_gainer": ranked[0] if ranked else None,
        "top_loser": ranked[-1] if ranked else None,
        "mood": mood_label,
        "mood_key": mood_key,
        "universe": total,
        "universe_label": universe_label,
        "sector_universe": len(sector_rows),
        "generated_ist": datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(),
    }


# ------------------------------------------------------------------
# AI Strategist's Read (NIM interprets the computed numbers)
# ------------------------------------------------------------------

def get_strategist_read(pulse: dict) -> dict:
    """
    2-sentence senior-strategist commentary from NVIDIA NIM, grounded on the
    already-computed pulse numbers. Best-effort — returns a rule-based fallback
    if the model is unavailable. {"text": str, "ai": bool}.
    """
    b = pulse.get("breadth", {})
    idx = pulse.get("indices", [])
    idx_line = ", ".join(
        f"{i['name']} {i['change']:+.2f}%" for i in idx
        if i.get("change") is not None
    ) or "indices flat/unavailable"
    leaders = ", ".join(f"{s['sector']} ({s['avg_chg']:+.1f}%)" for s in pulse.get("leaders", [])) or "none"
    laggards = ", ".join(f"{s['sector']} ({s['avg_chg']:+.1f}%)" for s in pulse.get("laggards", [])) or "none"

    fallback = (
        f"Breadth is {b.get('pct', 0)}% ({b.get('advancing', 0)} of {b.get('total', 0)} "
        f"large-caps advancing). Leaders: {leaders}. Laggards: {laggards}."
    )

    from agent.llm_client import complete

    prompt = (
        f"Indices: {idx_line}.\n"
        f"Breadth: {b.get('pct', 0)}% advancing ({b.get('advancing', 0)} of {b.get('total', 0)} large-caps).\n"
        f"Leading sectors: {leaders}.\n"
        f"Lagging sectors: {laggards}."
    )

    # "quick": two sentences off a small facts block. Falls back to the
    # deterministic breadth line rather than showing nothing.
    text = complete(_SYSTEM, prompt, task_shape="quick").strip()
    return {"text": text, "ai": True} if text else {"text": fallback, "ai": False}


__all__ = ["get_market_pulse", "get_strategist_read"]
