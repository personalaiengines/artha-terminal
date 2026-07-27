"""
ARTHA Terminal — JSON API for the Next.js front end.

Thin Starlette layer (starlette + uvicorn already in requirements — no new dep)
over the existing services/engines/DB. Every endpoint is defensive: on any
failure it returns {"ok": false} with 200 so the front end falls back to its
mock data instead of breaking. Slow live-market services are TTL-cached.

Run (dev):   python -m api.server        (or uvicorn api.server:app --port 8000)
Run (docker): a 'api' service in docker-compose reuses the main image.
"""
from __future__ import annotations
import asyncio
import contextlib
import logging
import time
import functools
from concurrent.futures import ThreadPoolExecutor

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

from db import get_connection

_POOL = ThreadPoolExecutor(max_workers=8)
# LLM/agent routes (stock analysis, F&O narrative, AI chat) run 10-90s per
# call — a separate, small pool keeps them from starving the fast DB-only
# routes above, which previously shared _POOL with them.
_LLM_POOL = ThreadPoolExecutor(max_workers=4)

# ---- tiny TTL cache for the slow, rate-limited live services ----
_cache: dict[str, tuple[float, object]] = {}

def cached(ttl: float):
    def deco(fn):
        @functools.wraps(fn)
        def wrap(*a):
            key = fn.__name__ + repr(a)
            hit = _cache.get(key)
            if hit and time.time() - hit[0] < ttl:
                return hit[1]
            val = fn(*a)
            _cache[key] = (time.time(), val)
            return val
        return wrap
    return deco

async def run(fn, *a):
    """Run a blocking service call off the event loop."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_POOL, fn, *a)

async def run_llm(fn, *a):
    """Run a slow LLM/agent call off the event loop, on the dedicated pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_LLM_POOL, fn, *a)

def ok(data):  # attach ok flag without clobbering service-provided one
    if isinstance(data, dict):
        data.setdefault("ok", True)
        return JSONResponse(data)
    return JSONResponse({"ok": True, "data": data})

def fail(e):
    return JSONResponse({"ok": False, "error": str(e)})


# ======================================================================
# Equity universe — pure DB (fast, reliable). Powers screener / watchlist
# / dashboard / stock header. Shaped to the front-end `Stock` type.
# ======================================================================
_RATING = lambda s: ("Strong Buy" if s >= 8.2 else "Buy" if s >= 6.8 else
                     "Hold" if s >= 5 else "Reduce" if s >= 3.5 else "Sell")

def _momentum_score(r1y, r6m, rsi):
    """Real, deterministic ARTHA score (0-10) from live price signals only —
    momentum + RSI regime. Not fundamentals (no working feed for those here)."""
    s = 5.0
    if r6m is not None: s += max(-2.5, min(2.5, r6m * 0.05))
    if r1y is not None: s += max(-2.0, min(2.0, r1y * 0.025))
    if rsi is not None:
        s += 1.0 if 45 <= rsi <= 65 else (-1.0 if (rsi > 78 or rsi < 25) else -0.2)
    return round(max(0.0, min(10.0, s)), 1)

def _num(v, d=None):
    try:
        return round(float(v), 2) if v is not None else d
    except (TypeError, ValueError):
        return d

def _ratio(v, lo, hi):
    """Sanitize a financial ratio: out-of-range or dirty DB values -> None,
    so the front end backfills from its baseline instead of showing garbage."""
    n = _num(v)
    return n if (n is not None and lo <= n <= hi) else None

@cached(60)
def _universe() -> list[dict]:
    with get_connection() as conn:
        c = conn.cursor()
        rows = c.execute("""
            SELECT m.symbol, m.company_name, COALESCE(m.sector, cm.sector, 'Other') AS sector,
                   m.market_cap_cr,
                   f.pe_ratio, f.pb_ratio, f.dividend_yield, f.roe, f.debt_to_equity,
                   cm.analysis_score, cm.return_1d, cm.ath, cm.atl, cm.dma_50, cm.dma_200,
                   cm.rsi_14, cm.beta, cm.return_1y, cm.return_6m
            FROM symbol_master m
            LEFT JOIN fundamentals f ON f.symbol = m.symbol
            LEFT JOIN computed_metrics cm ON cm.symbol = m.symbol
        """).fetchall()
        # One query for the latest close/volume per symbol (window function),
        # not one query per symbol in the loop below — was N+1 over the full
        # equity universe on every 60s cache miss.
        latest = c.execute("""
            SELECT symbol, close, volume FROM (
                SELECT symbol, close, volume,
                       ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC) AS rn
                FROM prices_daily
            ) WHERE rn = 1
        """).fetchall()
        latest_by_symbol = {r["symbol"]: r for r in latest}
        out = []
        for r in rows:
            d = dict(r)
            price_row = latest_by_symbol.get(d["symbol"])
            price = _num(price_row["close"]) if price_row else None
            vol = int(price_row["volume"]) if price_row and price_row["volume"] else None
            chg_pct = _num(d.get("return_1d"))
            score = _num(d.get("analysis_score")) or _momentum_score(
                _num(d.get("return_1y")), _num(d.get("return_6m")), _num(d.get("rsi_14")))
            out.append({
                "symbol": d["symbol"],
                "name": d["company_name"],
                "sector": d["sector"],
                "price": price,
                "changePct": chg_pct,
                "change": _num(price * chg_pct / 100) if (price and chg_pct is not None) else None,
                "mcapCr": _num(d.get("market_cap_cr")),
                "volume": vol,
                "pe": _ratio(d.get("pe_ratio"), 0, 1000),
                "pb": _ratio(d.get("pb_ratio"), 0, 100),
                "divYield": _ratio(d.get("dividend_yield"), 0, 30),
                "roe": _ratio(d.get("roe"), -100, 200),
                "debtEquity": _ratio(d.get("debt_to_equity"), 0, 50),
                "aiScore": score,
                "aiRating": _RATING(score) if score is not None else None,
                "health": round(min(100, max(0, score * 10))) if score is not None else None,
                "high52": _num(d.get("ath")),
                "low52": _num(d.get("atl")),
                "beta": _num(d.get("beta")),
                "rsi": _num(d.get("rsi_14")),
                "return1y": _num(d.get("return_1y")),
                "dma50": _num(d.get("dma_50")),
                "dma200": _num(d.get("dma_200")),
            })
        return out

async def universe(req):
    try:
        return JSONResponse({"ok": True, "items": await run(_universe)})
    except Exception as e:
        return fail(e)


@cached(120)
def _stock(sym: str) -> dict:
    sym = sym.upper()
    uni = {u["symbol"]: u for u in _universe()}
    base = uni.get(sym)
    with get_connection() as conn:
        c = conn.cursor()
        hist = c.execute(
            "SELECT date, open, high, low, close, volume FROM prices_daily "
            "WHERE symbol=? ORDER BY date DESC LIMIT 200", (sym,)).fetchall()
        history = [{"t": r["date"], "open": _num(r["open"]), "high": _num(r["high"]),
                    "low": _num(r["low"]), "close": _num(r["close"]),
                    "volume": int(r["volume"] or 0)} for r in reversed([dict(x) for x in hist])]
    return {"ok": bool(base), "stock": base, "history": history}

def _stock_analysis(sym: str) -> dict:
    """Grounded NIM narrative for one stock — real yfinance/DB snapshot facts,
    LLM only interprets. services/stock_analysis_llm.py existed but was never
    wired to an endpoint; this connects it. On-demand + cached (slow LLM call)."""
    from services.stock_data import get_live_stock_data
    from services.stock_analysis_llm import get_llm_analysis
    snap = get_live_stock_data(sym.upper())
    if not snap:
        return {"ok": False, "error": "No live snapshot available for this symbol."}
    res = get_llm_analysis(snap)
    return {"ok": res["ok"], "markdown": res["markdown"], "model": res["model"]}

async def stock_analysis(req):
    sym = req.path_params["symbol"].upper()
    try:
        return JSONResponse(await run_llm(_cached_call_arg, f"analysis:{sym}", _stock_analysis, sym, 3600))
    except Exception as e:
        return fail(e)

async def stock(req):
    try:
        return JSONResponse(await run(_stock, req.path_params["symbol"]))
    except Exception as e:
        return fail(e)


# ======================================================================
# Live market services — TTL-cached, defensive. Real when reachable.
# ======================================================================
async def pulse(req):
    try:
        from services.breadth import get_market_pulse
        return ok(await run(_cached_call, "pulse", get_market_pulse, 45))
    except Exception as e:
        return fail(e)

async def movers(req):
    try:
        from services.movers import get_top_movers
        return ok(await run(_cached_call, "movers", get_top_movers, 60))
    except Exception as e:
        return fail(e)

async def news(req):
    try:
        from services.market_news import get_live_market_news
        return ok(await run(_cached_call, "news", get_live_market_news, 900))
    except Exception as e:
        return fail(e)

async def flows(req):
    try:
        from services.institutional_flows import get_institutional_snapshot
        return ok(await run(_cached_call, "flows", get_institutional_snapshot, 600))
    except Exception as e:
        return fail(e)

async def global_board(req):
    try:
        from services.global_markets import get_global_board
        return ok(await run(_cached_call, "global", get_global_board, 60))
    except Exception as e:
        return fail(e)

def _events() -> dict:
    """Deterministic calendar (holidays/expiry/earnings) + NIM-AI-enriched macro
    events (CPI/central-bank/GDP, grounded on live search), merged. The AI layer
    is cached far longer (it's a slow ~40-90s NIM call) and best-effort — its
    absence never blocks the deterministic rows."""
    from services.market_events import get_market_events, get_ai_macro_events
    symbols = [u["symbol"] for u in _universe()][:25]
    base = get_market_events(symbols=symbols, days_ahead=14)

    ai_hit = _cache.get("events_ai")
    if ai_hit and time.time() - ai_hit[0] < 21600:  # 6h — slow + rate-limited
        ai = ai_hit[1]
    else:
        try:
            ai = get_ai_macro_events(days_ahead=14)
        except Exception:
            ai = {"india": [], "international": [], "ok": False}
        if ai.get("ok"):
            _cache["events_ai"] = (time.time(), ai)

    base["india"] = sorted(base["india"] + ai.get("india", []), key=lambda e: e["date"])
    base["international"] = sorted(base["international"] + ai.get("international", []), key=lambda e: e["date"])
    return base

async def events(req):
    try:
        return ok(await run(_cached_call, "events", _events, 3600))
    except Exception as e:
        return fail(e)

# UI index names -> fno_service keys (services.upstox.FNO_UNDERLYINGS).
_FNO_KEY = {"NIFTY": "nifty50", "NIFTY50": "nifty50", "BANKNIFTY": "banknifty",
            "BANK NIFTY": "banknifty", "SENSEX": "sensex"}

async def fno(req):
    idx = req.path_params.get("index", "NIFTY").upper()
    key = _FNO_KEY.get(idx, idx.lower())
    try:
        from services.fno_service import build_game_plan
        val = await run(_cached_call_arg, f"fno:{key}", build_game_plan, key, 120)
        return ok(val)
    except Exception as e:
        return fail(e)

def _fno_narrative(key: str) -> dict:
    """LLM narrative (free OpenRouter/NIM models) over the deterministic F&O
    game plan. services/fno_narrative.py existed but was never wired to an endpoint."""
    from services.fno_service import build_game_plan
    from services.fno_narrative import get_fno_narrative
    plan = _cached_call_arg(f"fno:{key}", build_game_plan, key, 120)
    return get_fno_narrative(plan)

async def fno_narrative_route(req):
    idx = req.path_params.get("index", "NIFTY").upper()
    key = _FNO_KEY.get(idx, idx.lower())
    try:
        return JSONResponse(await run_llm(_cached_call_arg, f"fno_narrative:{key}", _fno_narrative, key, 900))
    except Exception as e:
        return fail(e)

# module-level cached callers (so the ThreadPool sees a top-level fn)
def _cached_call(key, fn, ttl):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = fn()
    _cache[key] = (time.time(), val)
    return val

def _cached_call_arg(key, fn, arg, ttl):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = fn(arg)
    _cache[key] = (time.time(), val)
    return val


# ======================================================================
# AI Analyst — real agent for a detected symbol, else llm_client free-form.
# ======================================================================
_SYMS = None
def _known_symbols() -> set[str]:
    global _SYMS
    if _SYMS is None:
        _SYMS = {u["symbol"] for u in _universe()}
    return _SYMS

def _extract_symbol(q: str) -> str | None:
    up = q.upper()
    for s in _known_symbols():
        if s in up:
            return s
    return None

def _market_snapshot_text() -> tuple[str, list[str]]:
    """Compact, live market context (breadth, movers, indices, flows) for
    grounding the free-form analyst. Every part is best-effort — a failing
    service just drops its line, never the whole snapshot. Returns (text, used)
    where `used` names the live sources actually included."""
    parts, used = [], []
    try:
        from services.breadth import get_market_pulse
        p = _cached_call("pulse", get_market_pulse, 45) or {}
        b = p.get("breadth") or {}
        if b:
            parts.append(f"Market breadth: {b.get('advancing','?')} advancing / "
                         f"{b.get('declining','?')} declining ({b.get('pct','?')}% up)"
                         + (f", mood {p['mood']}" if p.get("mood") else ""))
            used.append("Market breadth")
        # Raw service keys: sectors carry `sector` + `avg_chg`.
        secs = p.get("sectors") or []
        if secs:
            top = ", ".join(f"{s.get('sector')} {s.get('avg_chg'):+.1f}%" for s in secs[:5] if s.get("avg_chg") is not None)
            if top:
                parts.append("Sector moves: " + top)
    except Exception:
        pass
    try:
        # Raw mover rows carry `symbol` + `pct`.
        from services.movers import get_top_movers
        m = _cached_call("movers", get_top_movers, 60) or {}
        g = ", ".join(f"{s['symbol']} {s.get('pct'):+.1f}%" for s in (m.get("gainers") or [])[:3] if s.get("pct") is not None)
        l = ", ".join(f"{s['symbol']} {s.get('pct'):+.1f}%" for s in (m.get("losers") or [])[:3] if s.get("pct") is not None)
        if g: parts.append("Top gainers: " + g)
        if l: parts.append("Top losers: " + l)
        if g or l: used.append("Movers")
    except Exception:
        pass
    try:
        # Raw index rows carry `name` + `change_pct`.
        from services.global_markets import get_global_board
        gb = _cached_call("global", get_global_board, 60) or {}
        idx = ", ".join(f"{i['name']} {i.get('change_pct'):+.1f}%" for i in (gb.get("indices") or [])[:5] if i.get("change_pct") is not None)
        if idx:
            parts.append("Indices: " + idx)
            used.append("Global board")
    except Exception:
        pass
    try:
        # Raw snapshot: fii/dii are {net,...} dicts plus *_stance labels.
        from services.institutional_flows import get_institutional_snapshot
        f = _cached_call("flows", get_institutional_snapshot, 600) or {}
        fii, dii = (f.get("fii") or {}), (f.get("dii") or {})
        if fii.get("net") is not None or dii.get("net") is not None:
            parts.append(f"Institutional flows (₹Cr, {f.get('date','recent')}): "
                         f"FII {fii.get('net')} ({f.get('fii_stance')}), "
                         f"DII {dii.get('net')} ({f.get('dii_stance')})")
            used.append("FII/DII flows")
    except Exception:
        pass
    return ("\n".join(parts), used)


def _web_search(query: str, n: int = 6) -> tuple[str, bool]:
    """Live web-search grounding (SerpAPI → SearxNG). Returns (text, used)."""
    try:
        import asyncio
        from services.search import SearchService

        async def _go():
            return await SearchService().search(query, limit=n, ttl_hours=2)
        loop = asyncio.new_event_loop()
        try:
            hits = loop.run_until_complete(_go())
        finally:
            loop.close()
        lines = [f"- {h.get('title','')}: {h.get('snippet','')} ({h.get('link','')})"
                 for h in (hits or []) if h.get("title")]
        return ("\n".join(lines), bool(lines))
    except Exception:
        return ("", False)


def _ai(question: str) -> dict:
    sym = _extract_symbol(question)
    if sym:
        from agent.orchestration import run_analysis_sync
        res = run_analysis_sync(sym, "deep_dive")
        content = res.get("content")
        if isinstance(content, dict):
            content = content.get("summary") or content.get("verdict") or str(content)
        tools = [t.get("name") if isinstance(t, dict) else str(t) for t in (res.get("tool_calls") or [])]
        return {"ok": bool(content), "answer": content or "", "symbol": sym,
                "tools": tools, "model": res.get("model_used"), "cards": [sym]}

    # No symbol → GROUNDED free-form: inject live market context + live web
    # search so the model answers with real data instead of disclaiming that it
    # "can't access live data". Both are best-effort; the model still answers if
    # they're empty, just less specifically.
    ctx, ctx_used = _market_snapshot_text()
    web, web_used = _web_search(question)
    tools = list(ctx_used) + (["Web search"] if web_used else [])

    grounding = ""
    if ctx:
        grounding += f"\n\nLIVE MARKET DATA (as of now):\n{ctx}"
    if web:
        grounding += f"\n\nLIVE WEB SEARCH RESULTS for the question:\n{web}"

    system = (
        "You are ARTHA, an equity research analyst for Indian markets (NSE/BSE). "
        "You DO have access to live market data and web search — it is provided "
        "to you below. Ground every claim in that data, cite figures from it, and "
        "never say you cannot access live or real-time data. If the provided data "
        "doesn't cover something, say so specifically. Be concise. End by noting "
        "this is research, not investment advice." + grounding
    )
    from agent.llm_client import ModelRouter
    client = ModelRouter()
    import asyncio
    msgs = [{"role": "system", "content": system},
            {"role": "user", "content": question}]
    loop = asyncio.new_event_loop()
    try:
        resp = loop.run_until_complete(client.chat(msgs))
    finally:
        loop.close()
    answer = ""
    model = None
    try:
        answer = resp["choices"][0]["message"]["content"]
        model = resp.get("model")
    except Exception:
        answer = ""
    return {"ok": bool(answer), "answer": answer, "symbol": None,
            "tools": tools, "model": model, "cards": []}

async def ai(req):
    try:
        body = await req.json()
        q = (body.get("q") or "").strip()
        if not q:
            return JSONResponse({"ok": False, "error": "empty query"})
        return JSONResponse(await run_llm(_ai, q))
    except Exception as e:
        return fail(e)


def _brief() -> dict:
    """AI-generated executive market brief, grounded on the live snapshot. Short
    (2-3 sentences). Falls back to ok:false so the dashboard keeps its
    deterministic templated line if the LLM is unavailable."""
    ctx, used = _market_snapshot_text()
    if not ctx:
        return {"ok": False, "brief": "", "sources": []}
    system = (
        "You are ARTHA, an equity research desk. Write a punchy 2-3 sentence "
        "executive brief on the Indian market RIGHT NOW, grounded strictly in the "
        "live data provided. Lead with breadth/direction, then flows or a notable "
        "mover. No preamble, no bullet points, no disclaimer.\n\nLIVE DATA:\n" + ctx
    )
    from agent.llm_client import ModelRouter
    client = ModelRouter()
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        resp = loop.run_until_complete(client.chat(
            [{"role": "system", "content": system},
             {"role": "user", "content": "Give me today's market brief."}]))
    finally:
        loop.close()
    try:
        brief = resp["choices"][0]["message"]["content"].strip()
    except Exception:
        brief = ""
    return {"ok": bool(brief), "brief": brief, "sources": used}


async def brief(req):
    try:
        return JSONResponse(await run_llm(_cached_call, "brief", _brief, 900))
    except Exception as e:
        return fail(e)


# ======================================================================
# Alerts — real persistence (create/list/delete). Own tiny table.
# ======================================================================
def _ensure_alerts():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                type TEXT NOT NULL,
                condition TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.commit()

async def alerts_list(req):
    try:
        _ensure_alerts()
        with get_connection() as conn:
            rows = conn.execute("SELECT id, symbol, type, condition, status, created FROM alerts ORDER BY created DESC").fetchall()
        return JSONResponse({"ok": True, "items": [dict(r) for r in rows]})
    except Exception as e:
        return fail(e)

async def alerts_create(req):
    try:
        _ensure_alerts()
        b = await req.json()
        sym = (b.get("symbol") or "").upper().strip()
        typ = (b.get("type") or "price").strip()
        cond = (b.get("condition") or "").strip()
        if not sym or not cond:
            return JSONResponse({"ok": False, "error": "symbol and condition required"})
        with get_connection() as conn:
            cur = conn.execute("INSERT INTO alerts (symbol, type, condition, status) VALUES (?,?,?, 'active')", (sym, typ, cond))
            conn.commit()
            new_id = cur.lastrowid
        return JSONResponse({"ok": True, "id": new_id})
    except Exception as e:
        return fail(e)

async def alerts_delete(req):
    try:
        _ensure_alerts()
        aid = int(req.path_params["id"])
        with get_connection() as conn:
            conn.execute("DELETE FROM alerts WHERE id=?", (aid,))
            conn.commit()
        return JSONResponse({"ok": True})
    except Exception as e:
        return fail(e)


# ======================================================================
# Upstox auth + system status — powers the global "authorize" banner.
# ======================================================================
def _upstox_status() -> dict:
    from services.upstox_auth import check_access_token, authorize_url, token_saved_at
    st = check_access_token()  # {"status": "ok"|"expired"|"missing"|"error", ...}
    return {"status": st.get("status"), "name": st.get("name"),
            "login_url": authorize_url(), "saved_at": token_saved_at()}

async def upstox_status(req):
    try:
        return JSONResponse({"ok": True, **await run(_cached_call, "upstox_status", _upstox_status, 60)})
    except Exception as e:
        return fail(e)

async def upstox_token(req):
    """Exchange an OAuth code (or full redirect URL) for a fresh daily token."""
    try:
        body = await req.json()
        from services.upstox_auth import exchange_code
        res = await run(exchange_code, (body.get("code") or ""))
        _cache.pop("upstox_status", None)  # status changed — drop the cache
        return JSONResponse(res if isinstance(res, dict) else {"ok": False})
    except Exception as e:
        return fail(e)

def _system_status() -> dict:
    """One aggregate for the UI banner: what's healthy, what needs the user."""
    import os
    up = _upstox_status()
    return {
        "upstox": up,
        "llm": {"openrouter": bool(os.getenv("OPENROUTER_API_KEY")),
                "nvidia": bool(os.getenv("NVIDIA_API_KEY"))},
        "db_symbols": len(_universe()),
    }

async def system_status(req):
    try:
        return JSONResponse({"ok": True, **await run(_cached_call, "system_status", _system_status, 60)})
    except Exception as e:
        return fail(e)


def _holdings() -> dict:
    """Real portfolio holdings via the Upstox daily token. No mock — returns
    ok:false with the auth status so the UI can prompt a re-authorize."""
    from services.upstox import UpstoxClient
    import asyncio
    res = asyncio.run(UpstoxClient().get_portfolio_holdings())
    if res.get("status") != "ok":
        return {"ok": False, "status": res.get("status"), "message": res.get("message"), "items": []}
    items = []
    for h in res.get("data", []) or []:
        qty = h.get("quantity") or 0
        avg = h.get("average_price") or 0
        ltp = h.get("last_price") or h.get("close_price") or 0
        invested, current = qty * avg, qty * ltp
        items.append({
            "symbol": h.get("trading_symbol") or h.get("tradingsymbol") or "",
            "name": h.get("company_name") or h.get("trading_symbol") or "",
            "qty": qty, "avg": avg, "price": ltp,
            "invested": invested, "current": current,
            "pnl": h.get("pnl") if h.get("pnl") is not None else current - invested,
            "pnlPct": ((current - invested) / invested * 100) if invested else 0,
            "dayChange": h.get("day_change") or 0,
        })
    return {"ok": True, "status": "ok", "items": items}

async def holdings(req):
    try:
        return JSONResponse(await run(_cached_call, "holdings", _holdings, 120))
    except Exception as e:
        return fail(e)


async def health(req):
    return JSONResponse({"ok": True, "service": "artha-api"})


# ======================================================================
# Ingestion monitor — last run / next cycle / success per ETL job, powers
# the Alerts-page ingestion status card.
# ======================================================================
def _ingestion_status() -> dict:
    from ingestion.scheduler import get_ingestion_status
    return {"jobs": get_ingestion_status()}

async def ingestion_status(req):
    try:
        return JSONResponse({"ok": True, **await run(_cached_call, "ingestion_status", _ingestion_status, 30)})
    except Exception as e:
        return fail(e)


routes = [
    Route("/api/health", health),
    Route("/api/universe", universe),
    Route("/api/stock/{symbol}", stock),
    Route("/api/stock/{symbol}/analysis", stock_analysis),
    Route("/api/pulse", pulse),
    Route("/api/movers", movers),
    Route("/api/news", news),
    Route("/api/flows", flows),
    Route("/api/global", global_board),
    Route("/api/events", events),
    Route("/api/fno/{index}", fno),
    Route("/api/fno/{index}/narrative", fno_narrative_route),
    Route("/api/ai", ai, methods=["POST"]),
    Route("/api/brief", brief),
    Route("/api/alerts", alerts_list, methods=["GET"]),
    Route("/api/alerts", alerts_create, methods=["POST"]),
    Route("/api/alerts/{id}", alerts_delete, methods=["DELETE"]),
    Route("/api/holdings", holdings),
    Route("/api/upstox/status", upstox_status),
    Route("/api/upstox/token", upstox_token, methods=["POST"]),
    Route("/api/system/status", system_status),
    Route("/api/ingestion/status", ingestion_status),
]

@contextlib.asynccontextmanager
async def _lifespan(app):
    """Apply DB schema/migrations, then start the nightly ETL scheduler
    in-process. The production image has no ENTRYPOINT (scripts/entrypoint.sh
    is copied in but never invoked — CMD jumps straight to uvicorn), so
    schema.sql was never actually applied inside the container; doing it here
    guarantees it runs on every start, in docker or local. The scheduler
    previously existed but nothing ever called it either — no automatic
    ingestion was running, just whatever got triggered manually. Both guarded
    so a startup problem never takes the API down with it."""
    try:
        from db import init_database
        init_database()
    except Exception as e:
        logging.getLogger("api.server").error(f"DB init/migration failed: {e}")
    try:
        from ingestion.scheduler import start_scheduler
        start_scheduler()
    except Exception as e:
        logging.getLogger("api.server").error(f"Ingestion scheduler failed to start: {e}")
    yield
    try:
        from ingestion.scheduler import stop_scheduler
        stop_scheduler()
    except Exception:
        pass

app = Starlette(
    routes=routes,
    lifespan=_lifespan,
    middleware=[Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"])],
)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
