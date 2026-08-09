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
import re
import time
import functools
import threading
from concurrent.futures import ThreadPoolExecutor

from starlette.applications import Starlette
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route, WebSocketRoute
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

from api.ws import ws_endpoint, manager as ws_manager
from api.udf import routes as udf_routes

from db import get_connection

# httpx logs the full request URL at INFO. Several upstreams take their
# credential as a query parameter (SerpAPI `api_key=`, Finnhub `token=`), so
# every search wrote a live key into the container logs in plaintext. WARNING
# keeps the failures and drops the URL line.
logging.getLogger("httpx").setLevel(logging.WARNING)

_POOL = ThreadPoolExecutor(max_workers=8)
# LLM/agent routes (stock analysis, F&O narrative, AI chat) run 10-90s per
# call — a separate, small pool keeps them from starving the fast DB-only
# routes above, which previously shared _POOL with them.
# 4 -> 12: the debate layer (agent/debate.py) added 3 extra sequential LLM
# calls to every deep_dive/verdict analysis, so each request now holds a
# worker noticeably longer. With only 4 workers, a few concurrent slow
# analyses starved this pool entirely — even /api/brief (a single quick
# call) would queue behind them indefinitely. These are I/O-bound waits on
# network calls, not CPU-bound, so more threads is cheap.
_LLM_POOL = ThreadPoolExecutor(max_workers=12)

# ---- tiny TTL cache for the slow, rate-limited live services ----
#
# Stale-while-revalidate. The market-data services behind these keys take
# 2.5-6.3s (yfinance batches of 100+ tickers, NSE fetches), and a plain TTL
# cache makes exactly one unlucky user per TTL window pay that full cost —
# the page just hangs for them. Instead: serve the stale value instantly and
# refresh in the background, so only the very first caller after a cold start
# ever blocks.
_cache: dict[str, tuple[float, object]] = {}
_refreshing: set[str] = set()
_refresh_lock = threading.Lock()
# Small dedicated pool: refreshes must never contend with request handlers
# for _POOL workers, or a slow refresh would stall real requests.
_REFRESH_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="cache-refresh")

# Keys are per-argument (`_cached_call_arg` builds "hist:30:A,B,C"), so an
# unbounded dict grows with every distinct symbol set a client ever asks for.
_CACHE_MAX = 256


def _cache_put(key: str, val: object) -> None:
    """Store and evict oldest-first. `dict` is insertion-ordered, so the first
    key is the oldest inserted — good enough here; nothing needs true LRU.
    ponytail: FIFO, not LRU. Swap in an OrderedDict/move_to_end if a hot key
    ever gets evicted while still being read.

    A FAILURE IS NEVER CACHED. One transient upstream blip used to be frozen
    for the whole TTL: `/api/fno/nifty50` served
    {"ok": false, "error": "no option expiries available"} in 0.0s while
    `/api/fno/nifty50/expiries` was concurrently returning all 18 of them, and
    `/api/positions` served a blank error against a healthy Upstox session.
    Both recovered the moment the process restarted, which is the tell.
    Refusing to store the failure costs a retry on the next request — the
    endpoint is broken anyway — and it self-heals instead of waiting out
    a 15-to-60-minute TTL.
    """
    if isinstance(val, dict) and val.get("ok") is False:
        logging.getLogger("api.cache").warning(
            "not caching failed result for %s: %s", key, val.get("error") or val.get("message") or "")
        return
    _cache[key] = (time.time(), val)
    while len(_cache) > _CACHE_MAX:
        _cache.pop(next(iter(_cache)))


def _swr(key: str, produce, ttl: float):
    """Return cached value, refreshing in the background once it goes stale.

    `produce` is a zero-arg callable. Blocks only when there is nothing cached
    at all (cold start); otherwise returns immediately, stale or fresh.
    """
    hit = _cache.get(key)
    now = time.time()

    if hit and now - hit[0] < ttl:
        return hit[1]

    if hit is None:
        val = produce()
        _cache_put(key, val)
        return val

    # Stale: hand back the old value now, kick off a single refresh.
    with _refresh_lock:
        already = key in _refreshing
        if not already:
            _refreshing.add(key)

    if not already:
        def _refresh():
            try:
                val = produce()
                _cache_put(key, val)
            except Exception as e:
                # Keep serving the stale value; a failed refresh must not
                # evict good data or surface as a request error.
                logging.getLogger("api.cache").warning(f"background refresh failed for {key}: {e}")
            finally:
                with _refresh_lock:
                    _refreshing.discard(key)
        _REFRESH_POOL.submit(_refresh)

    return hit[1]


def cached(ttl: float):
    def deco(fn):
        @functools.wraps(fn)
        def wrap(*a):
            return _swr(fn.__name__ + repr(a), lambda: fn(*a), ttl)
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

async def unhandled(req, exc):
    """One place where every route's failure turns into {"ok": false}.

    Every handler used to carry its own identical `try/except: return fail(e)`,
    which also meant a broken endpoint logged nothing — the UI silently fell
    back to mock data and the cause was invisible. Starlette re-raises after
    this response is sent, so uvicorn logs the traceback as well.
    """
    logging.getLogger("api.server").warning(f"{req.url.path} failed: {exc}")
    # The exception text stays in the log: it carries SQLite messages and
    # absolute file paths. The client gets a fixed string and a real 5xx, so
    # monitoring actually sees the failure instead of a 200.
    return JSONResponse({"ok": False, "error": "internal error"}, status_code=500)


# ======================================================================
# Equity universe — pure DB (fast, reliable). Powers screener / watchlist
# / dashboard / stock header. Shaped to the front-end `Stock` type.
# ======================================================================
# Soft signals only — the same token set the LLM contract uses (agent/prompts.py).
# Bands are collapsed from the old five, not retuned: a symbol lands in the same
# tone bucket it did before, only the word changed.
_RATING = lambda s: ("WATCH" if s >= 6.8 else "HOLD" if s >= 5 else "REVIEW")

def _momentum_score(r1y, r6m, rsi):
    """Real, deterministic ARTHA score (0-10) from live price signals only —
    momentum + RSI regime. Not fundamentals (no working feed for those here).

    Returns None when NONE of the inputs exist. Previously this returned the
    bare 5.0 baseline in that case, so every symbol with no price history at
    all (~half the universe) rendered a confident "5.0 / Hold / health 50" —
    a fabricated number presented as analysis. No data must read as no score.
    """
    if r1y is None and r6m is None and rsi is None:
        return None
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
            SELECT m.symbol, m.company_name,
                   COALESCE(im.industry, m.sector, cm.sector, 'Other') AS sector,
                   m.market_cap_cr,
                   f.pe_ratio, f.pb_ratio, f.dividend_yield, f.roe, f.debt_to_equity,
                   cm.analysis_score, cm.return_1d, cm.ath, cm.atl, cm.dma_50, cm.dma_200,
                   cm.rsi_14, cm.beta, cm.return_1y, cm.return_6m
            FROM symbol_master m
            LEFT JOIN fundamentals f ON f.symbol = m.symbol
            LEFT JOIN computed_metrics cm ON cm.symbol = m.symbol
            -- NSE's own industry label wins over yfinance's taxonomy.
            --
            -- Two vocabularies were living in this one column: NSE's
            -- ("Information Technology", "Automobile and Auto Components") for
            -- indexed stocks, yfinance's ("Technology", "Consumer Cyclical")
            -- for the rest. Market-breadth reports the NSE names, so clicking
            -- "Information Technology" on the sector heatmap filtered the
            -- screener for a label no row in it carried, and returned nothing.
            -- One symbol can sit in several indices; they all carry the same
            -- industry, so MIN() just picks it deterministically.
            LEFT JOIN (SELECT symbol, MIN(industry) AS industry
                         FROM index_members WHERE industry IS NOT NULL
                        GROUP BY symbol) im ON im.symbol = m.symbol
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
            # Explicit None check, not `or` — a legitimately computed score of
            # 0.0 is falsy and would otherwise be discarded for the fallback.
            # `scoreKind` tells the UI which it got: a full fundamentals-based
            # ScorecardEngine result, or the momentum-only heuristic. Labelling
            # a momentum number as a full "AI Score" overstates what it knows.
            score = _num(d.get("analysis_score"))
            score_kind = "scorecard" if score is not None else None
            if score is None:
                score = _momentum_score(
                    _num(d.get("return_1y")), _num(d.get("return_6m")), _num(d.get("rsi_14")))
                score_kind = "momentum" if score is not None else None
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
                "scoreKind": score_kind,
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
    return JSONResponse({"ok": True, "items": await run(_universe)})


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
    return JSONResponse(await run_llm(_cached_call_arg, f"analysis:{sym}", _stock_analysis, sym, 3600))

async def stock(req):
    return JSONResponse(await run(_stock, req.path_params["symbol"]))


# ======================================================================
# Live market services — TTL-cached, defensive. Real when reachable.
# ======================================================================
def _pulse() -> dict:
    """Market pulse, falling back to the last good snapshot.

    Breadth and sector rotation depend on yfinance + Upstox + the DB, so they
    can come back empty on a cold start, a rate-limited upstream, or a slow
    call that the web route times out on. Serving the last known-good snapshot
    (flagged stale, with the timestamp it was good at) beats an empty heatmap —
    and beats the client substituting a differently-shaped computation of its
    own, which is what it used to do.
    """
    from services.breadth import get_market_pulse
    from services.last_good import serve
    return serve("pulse", get_market_pulse, is_good=lambda v: bool(v.get("sectors")))

async def pulse(req):
    return ok(await run(_cached_call, "pulse", _pulse, 180))

async def movers(req):
    from services.movers import get_top_movers
    return ok(await run(_cached_call, "movers", get_top_movers, 300))

async def data_health(req):
    """What is not live right now, and what is being served instead.

    Short TTL: this is what the UI's "data is not live" banner reads, and a
    user who has just re-authorized Upstox should see it clear promptly.
    """
    from services.data_health import get_data_health
    return JSONResponse(await run(_cached_call, "data_health", get_data_health, 30))

async def india_board(req):
    """Home indices + Gift Nifty with session state. 20s TTL — the dashboard
    ticker polls this, and while the market is open the levels move."""
    from services.global_markets import get_india_board
    return ok(await run(_cached_call, "india", get_india_board, 20))

def _news_from_cache_or_live() -> dict:
    """Prefer the scheduler-precomputed cache (agent_cache, refreshed every
    ~10 min by ingestion.scheduler._run_market_news_curation — HSTR-lite:
    curation moved off the request path) over a live call. Falls back to a
    live call on cold start (no row yet) or if the row has expired."""
    import json
    from datetime import datetime
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT content_json, expires_at FROM agent_cache WHERE key='market_news'"
            ).fetchone()
        if row and row["expires_at"] > datetime.now().isoformat():
            return json.loads(row["content_json"])
    except Exception:
        pass
    from services.market_news import get_live_market_news
    return get_live_market_news()

async def news(req):
    payload = await run(_cached_call, "news", _news_from_cache_or_live, 900)
    # The briefing carries the phase it was WRITTEN in (briefing.phase); this is
    # the phase right NOW. They differ for up to one curation cycle around the
    # bell, and the UI needs both — otherwise a 15-minute cache leaves the page
    # captioned "Pre-Open" while the market is already trading.
    if isinstance(payload, dict):
        from services.market_news import session_phase
        payload = {**payload, "phase": session_phase()}
    return ok(payload)

async def flows(req):
    from services.institutional_flows import get_institutional_snapshot
    return ok(await run(_cached_call, "flows", get_institutional_snapshot, 600))

async def global_board(req):
    from services.global_markets import get_global_board
    return ok(await run(_cached_call, "global", get_global_board, 300))

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
            _cache_put("events_ai", ai)

    _key = lambda e: (e["date"], e.get("time_ist") or "")
    base["india"] = sorted(base["india"] + ai.get("india", []), key=_key)
    base["international"] = sorted(base["international"] + ai.get("international", []), key=_key)
    return base

async def events(req):
    return ok(await run(_cached_call, "events", _events, 3600))

# UI index names -> fno_service keys (services.upstox.FNO_UNDERLYINGS).
_FNO_KEY = {"NIFTY": "nifty50", "NIFTY50": "nifty50", "BANKNIFTY": "banknifty",
            "BANK NIFTY": "banknifty", "SENSEX": "sensex"}

# India VIX percentile window — one trailing year of sessions (R13).
_VIX_WINDOW = 252

# Shape guard for a user-supplied ?expiry=. Membership is checked upstream in
# fno_service._build_async (where the listed set lives); this only keeps junk
# out of the cache keys it would otherwise mint one of per distinct value.
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

def _fno_index(req) -> str:
    """Path index name -> fno_service key."""
    idx = req.path_params.get("index", "NIFTY").upper()
    return _FNO_KEY.get(idx, idx.lower())

def _fno_plan(key: str, expiry: str | None = None) -> dict:
    """
    The cached game plan plus India VIX in the only context that means
    anything: its own trailing-252-session percentile.

    Attached HERE, not in fno_service: the VIX history lives in prices_daily
    (ingestion/index_history.py writes INDIAVIX), and services.fno_analysis is
    deliberately I/O-free. `_candles` carries the dates, which `_history` drops
    — so `vix_as_of` comes from the same read as the closes, not a second query.
    """
    from services.fno_service import build_game_plan
    from services.fno_analysis import percentile_rank
    # No expiry -> the original key, so the narrative route below still shares
    # this cache entry instead of building the same plan a second time.
    ck = f"fno:{key}:{expiry}" if expiry else f"fno:{key}"
    plan = _swr(ck, lambda: build_game_plan(key, expiry), 120)
    if not plan.get("ok"):
        return plan
    rows = _candles("INDIAVIX", _VIX_WINDOW)
    closes = [r["close"] for r in rows]
    return {**plan,
            "vix_percentile": percentile_rank(closes, plan.get("india_vix")),
            "vix_window": len(closes),
            "vix_as_of": rows[-1]["t"] if rows else None}

async def fno(req):
    expiry = req.query_params.get("expiry") or None
    if expiry and not _ISO_DATE.match(expiry):
        return JSONResponse({"ok": False, "error": "invalid expiry"}, status_code=400)
    return ok(await run(_fno_plan, _fno_index(req), expiry))

def _fno_expiries(key: str) -> dict:
    """Every listed expiry for one index. An expiry list changes at most daily,
    hence the hour — but an empty/failed list is not an hour-good answer, so it
    is dropped from the cache and the next caller retries."""
    from services.fno_service import get_expiries
    ck = f"fno_expiries:{key}"
    res = _swr(ck, lambda: get_expiries(key), 3600)
    if not res.get("ok"):
        _cache.pop(ck, None)
    return res

async def fno_expiries(req):
    return JSONResponse(await run(_fno_expiries, _fno_index(req)))

def _fno_term(key: str) -> dict:
    """ATM IV across the nearest few expiries (the cap travels as `cap`).

    A partial read — one expiry that failed or carried no live ATM IV — is
    degraded, not good for 15 minutes: it is evicted so the next caller refetches
    rather than being served a short curve as if it were the whole one.

    ponytail: an index whose far expiries are unpriced ALL session (BANKNIFTY
    today) therefore refetches on every request — 4 upstream calls, ~1.2s. Give
    the degraded case its own short TTL if a page ever polls this hot."""
    from services.fno_service import term_structure
    ck = f"fno_term:{key}"
    res = _swr(ck, lambda: term_structure(key), 900)
    if not res.get("complete"):
        _cache.pop(ck, None)
    return res

async def fno_term(req):
    return JSONResponse(await run(_fno_term, _fno_index(req)))

def _fno_narrative(key: str) -> dict:
    """The /options AI surface: microstructure — what the skew across strikes and
    the term structure across expiries price in (services/fno_narrative.py).

    The term structure is a separate read, so it comes from the same 900s-cached
    helper the /term route serves rather than a fresh set of chain fetches."""
    from services.fno_service import build_game_plan
    from services.fno_narrative import get_fno_narrative
    plan = _cached_call_arg(f"fno:{key}", build_game_plan, key, 120)
    return get_fno_narrative(plan, _fno_term(key))

def _fno_oi_read(key: str) -> dict:
    """The /fno AI surface: where open interest moved this session and what that
    says about the writers' defence (services/fno_oi_read.py).

    Shares the `fno:{key}` plan entry with the route above — one chain fetch
    feeds both surfaces."""
    from services.fno_service import build_game_plan
    from services.fno_oi_read import get_oi_read
    plan = _cached_call_arg(f"fno:{key}", build_game_plan, key, 120)
    return get_oi_read(plan)

def _cached_llm(ck: str, fn, arg: str, ttl: float) -> dict:
    """Cache an LLM markdown surface — but only when it came back whole.

    A degraded answer (`ok: False`: the provider chain fell over mid-call, or a
    model replied without a single one of the requested sections) is evicted, so
    the next caller retries instead of being served the wreck for 15 minutes.
    This project has already been bitten by exactly that: a news read returned 2
    of 18 items after a mid-call 429 and cached it."""
    res = _swr(ck, lambda: fn(arg), ttl)
    if not (res or {}).get("ok"):
        _cache.pop(ck, None)
    return res

async def fno_narrative_route(req):
    key = _fno_index(req)
    return JSONResponse(await run_llm(_cached_llm, f"fno_narrative:{key}", _fno_narrative, key, 900))

async def fno_oi_read_route(req):
    key = _fno_index(req)
    return JSONResponse(await run_llm(_cached_llm, f"fno_oi_read:{key}", _fno_oi_read, key, 900))

# module-level cached callers (so the ThreadPool sees a top-level fn)
def _cached_call(key, fn, ttl):
    return _swr(key, fn, ttl)

def _cached_call_arg(key, fn, arg, ttl):
    return _swr(key, lambda: fn(arg), ttl)


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
    """First symbol genuinely mentioned, or None.

    Was a naive `if s in q.upper()` over an unordered set of 5173 symbols, so
    "Summarise this week's news" resolved to MARIS (inside "SUMMARISE") and
    "is the market overvalued" to VALUE — each triggering a full deep dive on
    an unrelated microcap. agent.chat matches on word boundaries instead.
    """
    from agent.chat import extract_symbols
    syms = extract_symbols(q, limit=1)
    return syms[0] if syms else None

def _market_snapshot_text() -> tuple[str, list[str]]:
    """Compact, live market context (breadth, movers, indices, flows) for
    grounding the free-form analyst. Every part is best-effort — a failing
    service just drops its line, never the whole snapshot. Returns (text, used)
    where `used` names the live sources actually included."""
    parts, used = [], []
    try:
        from services.breadth import get_market_pulse
        p = _cached_call("pulse", get_market_pulse, 180) or {}
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
        m = _cached_call("movers", get_top_movers, 300) or {}
        g = ", ".join(f"{s['symbol']} {s.get('pct'):+.1f}%" for s in (m.get("gainers") or [])[:3] if s.get("pct") is not None)
        l = ", ".join(f"{s['symbol']} {s.get('pct'):+.1f}%" for s in (m.get("losers") or [])[:3] if s.get("pct") is not None)
        if g: parts.append("Top gainers: " + g)
        if l: parts.append("Top losers: " + l)
        if g or l: used.append("Movers")
    except Exception:
        pass
    try:
        # Home board first — a brief about Indian markets that never states
        # where Nifty and Sensex actually closed is the main reason the old
        # one read as vague filler.
        from services.global_markets import get_india_board
        ib = _cached_call("india", get_india_board, 20) or {}
        rows = [i for i in (ib.get("indices") or []) if i.get("price") is not None]
        if rows:
            parts.append("Indian indices: " + ", ".join(
                f"{i['name']} {i['price']:,.0f}" + (f" ({i['change_pct']:+.2f}%)"
                                                    if i.get("change_pct") is not None else "")
                for i in rows))
            state = next((i["status"]["state"] for i in rows if i.get("status")), None)
            if state:
                parts.append(f"NSE/BSE session: {state}")
            used.append("Indian indices")
    except Exception:
        pass
    try:
        # Raw index rows carry `name` + `change_pct`.
        from services.global_markets import get_global_board
        gb = _cached_call("global", get_global_board, 300) or {}
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
    from agent.chat import extract_symbols, route_intent
    syms = extract_symbols(question)
    # Only a question actually asking for a workup earns the 8-tool, 3-debate-call
    # deep dive. Naming a stock while asking a one-line question does not.
    sym = syms[0] if syms and route_intent(question, syms) == "deep" else None
    if sym:
        from agent.orchestration import run_analysis_sync
        res = run_analysis_sync(sym, "deep_dive")
        content = res.get("content")
        if isinstance(content, dict):
            content = content.get("summary") or content.get("verdict") or str(content)
        tools = [t.get("tool") if isinstance(t, dict) else str(t) for t in (res.get("tool_calls") or [])]
        return {"ok": bool(content), "answer": content or "", "symbol": sym,
                "tools": tools, "model": res.get("model_used"), "cards": [sym]}

    # Same grounding and the same system prompt the streaming analyst uses.
    #
    # This path used to build its own blocks behind its own, much weaker prompt
    # — "ground every claim, be concise" and nothing about invented sources. It
    # answered a TCS price question with a close attributed to a "Kotak Neo
    # intraday quote" and a fabricated day range, neither of which exists in any
    # feed this app reads. Two prompts meant hardening one left the other wrong.
    from agent.chat import build_system, screen_display, screen_facts, symbol_facts
    intent = route_intent(question, syms)
    blocks, tools, prefix = [], [], ""

    if intent == "screen":
        block = screen_facts(question)
        if block:
            blocks.append(block)
            tools.append("ARTHA database")
            # Table rendered from the DB and prepended to the answer; the model
            # is told not to reproduce it. See agent.chat.screen_display.
            prefix = screen_display(block)
            if prefix:
                blocks.append(
                    "The table above has ALREADY been shown to the user verbatim. "
                    "Do NOT output a table, do not restate its rows, and do not "
                    "add columns to it. Write only the commentary that follows it.")
                prefix += "\n\n"
    for s in syms:
        blocks.append(symbol_facts(s))
    if syms:
        tools.append("ARTHA database")

    if intent in ("market", "portfolio", "deep", "screen"):
        ctx, ctx_used = _market_snapshot_text()
        if ctx:
            blocks.append(f"### Live market context\n{ctx}")
            tools += list(ctx_used)
    # Only a genuinely open question earns a web search. Firing it on a screen
    # is what let foreign listings into an answer about Indian pharma.
    web = ""
    if intent == "market":
        web, web_used = _web_search(question)
        if web:
            tools.append("Web search")

    system = build_system(intent, blocks)
    from agent.llm_client import ModelRouter, AllTiersExhausted
    client = ModelRouter()
    import asyncio
    # Web snippets are scraped from arbitrary third-party pages, so they stay
    # OUT of the system prompt — inside it they carried the same authority as
    # the grounding rules themselves. Delimited user-role message instead; the
    # GROUNDING contract (agent/prompts.py) tells the model to treat anything
    # between these markers as data, never as instructions.
    msgs = [{"role": "system", "content": system}]
    if web:
        from agent.prompts import fence_untrusted
        msgs.append({"role": "user", "content": fence_untrusted(web)})
    msgs.append({"role": "user", "content": question})
    loop = asyncio.new_event_loop()
    try:
        resp = loop.run_until_complete(client.chat(
            msgs, task_shape="deep" if intent in ("screen", "portfolio") else "quick"))
    except AllTiersExhausted as e:
        return {"ok": False, "error": "all_llm_tiers_exhausted", "detail": str(e),
                "symbol": None, "tools": tools, "cards": []}
    finally:
        loop.close()
    answer = ""
    model = None
    try:
        answer = resp["choices"][0]["message"]["content"] or ""
        model = resp.get("model")
    except Exception:
        answer = ""
    if not answer:
        # A provider can return 200 with empty content — reasoning models put the
        # chain of thought in `message.reasoning`, and a stop mid-way leaves
        # `content` blank. This used to return {"ok": false, "answer": ""} with no
        # log and no error, so the UI showed its scripted demo answer and the
        # failure was indistinguishable from a real reply. Say what happened.
        choice = (resp.get("choices") or [{}])[0] if isinstance(resp, dict) else {}
        logging.getLogger("api.server").warning(
            "empty answer from %s (finish_reason=%s, reasoning=%d chars)",
            resp.get("model") if isinstance(resp, dict) else "?",
            choice.get("finish_reason"),
            len((choice.get("message") or {}).get("reasoning") or ""))
        return {"ok": False, "error": "empty_answer", "answer": "",
                "detail": f"{resp.get('model') if isinstance(resp, dict) else 'model'} "
                          f"returned no answer text (finish_reason="
                          f"{choice.get('finish_reason')})",
                "symbol": syms[0] if syms else None,
                "tools": tools, "model": model, "cards": syms}
    return {"ok": True, "answer": prefix + answer,
            "symbol": syms[0] if syms else None,
            "tools": tools, "model": model, "cards": syms}

# A real question fits comfortably; past this it is either an accident or an
# attempt to blow a context window (and a tier's token quota) with one POST.
_MAX_QUESTION = 2000


async def ai(req):
    body = await req.json()
    q = (body.get("q") or "").strip()
    if not q:
        return JSONResponse({"ok": False, "error": "empty query"})
    if len(q) > _MAX_QUESTION:
        return JSONResponse({"ok": False, "error": "question too long"}, status_code=400)
    return JSONResponse(await run_llm(_ai, q))


# ---- Streaming chat (SSE) ----------------------------------------------
# The non-streaming /api/ai above stays for the dashboard's one-shot uses. The
# analyst page uses this: the client sees the routing decision, each grounding
# step and then the answer token by token, instead of a spinner for 20s
# followed by a fake typewriter replaying an already-finished response.

async def _sse_chat(q: str, history: list[dict]):
    import json as _json
    from agent import chat as agent_chat

    def _sse(event: str, payload: dict) -> str:
        return f"event: {event}\ndata: {_json.dumps(payload, default=str)}\n\n"

    try:
        # Grounding that needs blocking IO runs off the event loop, as elsewhere.
        # Same router agent_chat.answer() uses, history included — routing here
        # without it made follow-ups ("what about its debt?") look like market
        # questions and fire a needless web search.
        _, intent = await run(agent_chat.resolve, q, history)
        market_ctx, web_ctx = "", ""
        if intent in ("market", "portfolio", "deep", "screen"):
            market_ctx = (await run(_market_snapshot_text))[0]
        # Web search stays off for `screen`: the constituent table is the answer,
        # and searching "pharma stocks" returns US listings that then get mixed in.
        if intent == "market":
            yield _sse("status", {"stage": "tool", "label": "Searching the web"})
            web_ctx = (await run(_web_search, q))[0]

        async for event, payload in agent_chat.answer(
            q, history, market_context=market_ctx, web_context=web_ctx
        ):
            yield _sse(event, payload)
    except Exception as e:
        logging.getLogger("api.ai").exception("stream failed")
        yield _sse("error", {"message": f"Analysis failed: {e}"})
    finally:
        yield _sse("done", {})


async def ai_stream(req):
    try:
        body = await req.json()
    except Exception:
        body = {}
    q = (body.get("q") or "").strip()
    if not q:
        return JSONResponse({"ok": False, "error": "empty query"}, status_code=400)
    if len(q) > _MAX_QUESTION:
        return JSONResponse({"ok": False, "error": "question too long"}, status_code=400)
    return StreamingResponse(
        _sse_chat(q, body.get("history") or []),
        media_type="text/event-stream",
        # nginx/proxies buffer SSE into uselessness without these.
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no",
                 "Connection": "keep-alive"},
    )


def _brief() -> dict:
    """AI-generated executive market brief, grounded on the live snapshot.

    Was a 2-3 sentence one-liner that mostly restated the breadth percentage
    already shown next to it. Now a full round-up in plain English: where the
    indices are, what's leading and lagging, who's buying, the global cues and
    what to watch — every claim tied to a number in the snapshot. Markdown, so
    the dashboard renders headings/bullets instead of a wall of text.
    """
    ctx, used = _market_snapshot_text()
    if not ctx:
        return {"ok": False, "brief": "", "sources": []}
    # The shared contract first, then the format rules specific to this surface.
    # This prompt used to hand-roll its own grounding and style ("never invent a
    # figure", "no 'as an AI'") — a sixth copy of rules that live in
    # agent/prompts.py, so every hardening made there missed the dashboard brief.
    # Its bullet-list structure below is FORMAT, not grounding, so it stays and
    # wins over HOUSE_STYLE's general markdown guidance.
    from agent.prompts import COMPLIANCE, GROUNDING, HOUSE_STYLE
    system = (
        f"{GROUNDING}\n\n{HOUSE_STYLE}\n\n{COMPLIANCE}\n\n"
        "You are ARTHA, an equity research desk writing the daily market round-up "
        "for Indian markets (NSE/BSE). Write for an intelligent reader who is NOT "
        "a market professional.\n\n"
        "RULES\n"
        "- Plain, simple English. Short sentences. No jargon unless you explain it "
        "in the same breath (e.g. 'breadth — how many stocks rose versus fell').\n"
        "- Output a markdown BULLET LIST. Every line starts with '- ' followed by a "
        "bold label, then the point. Nothing else — no intro paragraph, no prose "
        "blocks between bullets.\n"
        "- Cover the whole market, one bullet each, in this order:\n"
        "  - **Headline** — is the market up, down or flat, and by how much.\n"
        "  - **Under the surface** — breadth, and whether the move is broad or narrow.\n"
        "  - **Sectors** — which parts of the market led and which lagged.\n"
        "  - **Movers** — the standout individual stocks, up and down.\n"
        "  - **Money flows** — what foreign (FII) and domestic (DII) institutions did, "
        "and what that usually signals.\n"
        "  - **Global cues** — how overseas markets and Gift Nifty are pointing.\n"
        "  - **Watch next** — 2-3 concrete things to keep an eye on.\n"
        "- One or two sentences per bullet, maximum. Skip any bullet the data "
        "doesn't cover — do not pad it with generalities.\n"
        # Preamble/sign-off/"as an AI" are HOUSE_STYLE's job. Only the
        # no-disclaimer rule is specific to this surface.
        "- No compliance disclaimer line; the page carries one already.\n\n"
        "LIVE DATA (this is everything you know; the market state is as of now):\n" + ctx
    )
    from agent.llm_client import ModelRouter, AllTiersExhausted
    client = ModelRouter()
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        resp = loop.run_until_complete(client.chat(
            [{"role": "system", "content": system},
             {"role": "user", "content": "Give me today's market brief."}],
            # "deep", not "quick": this is now a full multi-section round-up,
            # and the quick tier's small models drop sections and hallucinate
            # numbers when asked to hold this much context.
            task_shape="deep"))
    except AllTiersExhausted:
        return {"ok": False, "brief": "", "sources": used}
    finally:
        loop.close()
    try:
        brief = resp["choices"][0]["message"]["content"].strip()
    except Exception:
        brief = ""
    return {"ok": bool(brief), "brief": brief, "sources": used}


async def brief(req):
    return JSONResponse(await run_llm(_cached_call, "brief", _brief, 900))


# ======================================================================
# Alerts — real persistence (create/list/delete). Table lives in db/schema.sql.
# ======================================================================
async def alerts_list(req):
    with get_connection() as conn:
        rows = conn.execute("SELECT id, symbol, type, condition, status, created FROM alerts ORDER BY created DESC").fetchall()
    return JSONResponse({"ok": True, "items": [dict(r) for r in rows]})

async def alerts_create(req):
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

async def alerts_delete(req):
    aid = int(req.path_params["id"])
    with get_connection() as conn:
        conn.execute("DELETE FROM alerts WHERE id=?", (aid,))
        conn.commit()
    return JSONResponse({"ok": True})


# ======================================================================
# Watchlists — real persistence (multiple named lists of symbols). No
# hardcoded/mock lists — starts empty, user creates lists and adds symbols.
# Tables live in db/schema.sql.
# ======================================================================
async def watchlists_list(req):
    with get_connection() as conn:
        lists = conn.execute("SELECT id, name, created FROM watchlists ORDER BY created ASC").fetchall()
        items = conn.execute("SELECT list_id, symbol FROM watchlist_items ORDER BY added ASC").fetchall()
    by_list: dict[int, list[str]] = {}
    for it in items:
        by_list.setdefault(it["list_id"], []).append(it["symbol"])
    out = [{"id": l["id"], "name": l["name"], "created": l["created"],
            "symbols": by_list.get(l["id"], [])} for l in lists]
    return JSONResponse({"ok": True, "items": out})

async def watchlists_create(req):
    b = await req.json()
    name = (b.get("name") or "").strip()
    if not name:
        return JSONResponse({"ok": False, "error": "name required"})
    with get_connection() as conn:
        try:
            cur = conn.execute("INSERT INTO watchlists (name) VALUES (?)", (name,))
            conn.commit()
        except Exception:
            return JSONResponse({"ok": False, "error": "a list with that name already exists"})
        new_id = cur.lastrowid
    return JSONResponse({"ok": True, "id": new_id, "name": name})

async def watchlists_delete(req):
    lid = int(req.path_params["id"])
    with get_connection() as conn:
        # ponytail: FK enforcement is scoped to this connection so the declared
        # ON DELETE CASCADE on watchlist_items fires. Turning it on globally in
        # db/__init__.py is blocked on cleaning up the symbol_master orphans —
        # prices_daily/fundamentals/agent_cache already violate those FKs, so a
        # global pragma would make ingestion inserts raise IntegrityError.
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("DELETE FROM watchlists WHERE id=?", (lid,))
        conn.commit()
    return JSONResponse({"ok": True})

async def watchlist_add_symbol(req):
    lid = int(req.path_params["id"])
    b = await req.json()
    sym = (b.get("symbol") or "").upper().strip()
    if not sym:
        return JSONResponse({"ok": False, "error": "symbol required"})
    with get_connection() as conn:
        conn.execute("INSERT OR IGNORE INTO watchlist_items (list_id, symbol) VALUES (?,?)", (lid, sym))
        conn.commit()
    return JSONResponse({"ok": True})

async def watchlist_remove_symbol(req):
    lid = int(req.path_params["id"])
    sym = req.path_params["symbol"].upper()
    with get_connection() as conn:
        conn.execute("DELETE FROM watchlist_items WHERE list_id=? AND symbol=?", (lid, sym))
        conn.commit()
    return JSONResponse({"ok": True})


# ======================================================================
# Upstox auth + system status — powers the global "authorize" banner.
# ======================================================================
def _upstox_status() -> dict:
    from services.upstox_auth import check_access_token, authorize_url, token_saved_at
    st = check_access_token()  # {"status": "ok"|"expired"|"missing"|"error", ...}
    return {"status": st.get("status"), "name": st.get("name"),
            "login_url": authorize_url(), "saved_at": token_saved_at()}

async def upstox_status(req):
    return JSONResponse({"ok": True, **await run(_cached_call, "upstox_status", _upstox_status, 60)})

async def upstox_token(req):
    """Exchange an OAuth code (or full redirect URL) for a fresh daily token."""
    body = await req.json()
    from services.upstox_auth import exchange_code
    res = await run(exchange_code, (body.get("code") or ""))

    # Drop EVERY cache derived from Upstox auth, not just upstox_status.
    #
    # This is what made authorization look broken. The exchange succeeded and
    # returned 200, but the banner then re-read /api/system/status — a
    # different, still-warm cache entry — and kept announcing "authorization
    # has expired" for up to a minute afterwards. Stale-while-revalidate made
    # it worse: the first read after expiry still serves the old value. Users
    # reasonably concluded it had failed and logged in again; the logs show
    # three successful exchanges in 62 seconds.
    if isinstance(res, dict) and res.get("ok"):
        for key in ("upstox_status", "system_status", "data_health",
                    "holdings", "positions", "portfolio_curve"):
            _cache.pop(key, None)
    return JSONResponse(res if isinstance(res, dict) else {"ok": False})

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
    return JSONResponse({"ok": True, **await run(_cached_call, "system_status", _system_status, 60)})


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
        prev_close = h.get("close_price") or 0
        ltp = h.get("last_price") or prev_close or 0
        invested, current = qty * avg, qty * ltp
        # Upstox reports day_change as a flat 0.0 on this endpoint (verified live
        # against a real book), so deriving it from last_price - close_price is
        # the only correct source. Trusting the field made the whole book's day
        # P&L fall back to stale universe closes and print a profit on a losing day.
        day_change = (ltp - prev_close) if (ltp and prev_close) else None
        items.append({
            "symbol": h.get("trading_symbol") or h.get("tradingsymbol") or "",
            "name": h.get("company_name") or h.get("trading_symbol") or "",
            "qty": qty, "avg": avg, "price": ltp, "prevClose": prev_close or None,
            "invested": invested, "current": current,
            "pnl": h.get("pnl") if h.get("pnl") is not None else current - invested,
            "pnlPct": ((current - invested) / invested * 100) if invested else 0,
            "dayChange": day_change,
            "dayChangePct": (day_change / prev_close * 100) if day_change is not None and prev_close else None,
        })
    return {"ok": True, "status": "ok", "items": items}

async def holdings(req):
    return JSONResponse(await run(_cached_call, "holdings", _holdings, 120))


# Derivatives segments. An equity position in the same book is not part of the
# F&O surface and is dropped rather than shown under an F&O heading.
_FNO_EXCHANGES = ("NFO", "BFO")

def _positions() -> dict:
    """The user's live F&O positions — READ-ONLY.

    Reads the book and nothing else: no order is placed, modified or cancelled
    here or anywhere this route reaches. Only the display fields below leave the
    process — the raw row's ~29 keys (account-level values, day-wise breakdowns)
    are not forwarded and nothing here logs a symbol, a size or a P&L. The two
    non-display fields, `key` and `multiplier`, are properties of the CONTRACT
    rather than of the account: the same pair is public for anyone holding that
    instrument, and they exist so the browser can subscribe the row to the tick
    stream (see web/components/widgets/positions-panel.tsx).

    An expired/missing token is ok:false + the auth status, so the UI prompts a
    re-authorize. An empty book is a real answer: ok:true with items: [].
    """
    from services.upstox import UpstoxClient
    import asyncio
    res = asyncio.run(UpstoxClient().get_positions())
    if res.get("status") != "ok":
        return {"ok": False, "status": res.get("status"), "message": res.get("message"), "items": []}
    items, done = [], []
    for p in res.get("data", []) or []:
        if (p.get("exchange") or "").upper() not in _FNO_EXCHANGES:
            continue
        qty = p.get("quantity") or 0
        row = {
            "symbol": p.get("trading_symbol") or p.get("tradingsymbol") or "",
            # The Upstox instrument key ("NSE_FO|46617"). Public instrument
            # identity, not account data — forwarded so the browser can put the
            # contract on the tick stream instead of waiting out the poll. Every
            # other field here is a REST snapshot up to 30s old; the book is the
            # one table on the page where that is visible as a frozen LTP.
            "key": p.get("instrument_token"),
            # Contract size per unit of `qty`. 1 for every Indian F&O contract
            # today (quantity already carries lots x lot size), but it is what
            # a P&L delta must be multiplied by, so take it from the broker
            # rather than assuming.
            "multiplier": p.get("multiplier"),
            "qty": qty,
            # Upstox has no side field: the sign of the net quantity is it.
            "side": "LONG" if qty > 0 else "SHORT",
            "avg": p.get("average_price"),
            "ltp": p.get("last_price"),
            "pnl": p.get("pnl"),
            "realized": p.get("realised"),
            "unrealized": p.get("unrealised"),
            "product": p.get("product"),
            "exchange": p.get("exchange"),
        }
        if not qty:
            # Upstox keeps a row for every contract traded today, including the
            # ones squared off — net quantity 0. Those are not open positions and
            # must not render as one. They were previously counted and thrown
            # away, which discarded the day's *booked* P&L: the tracker needs
            # exactly that, so they are returned separately instead.
            done.append(row)
            continue
        items.append(row)

    # Realised is booked on every row — a squared-off contract's whole P&L lives
    # there — while unrealised only exists while something is still open.
    from services.fno_pnl import snapshot
    totals = snapshot(items + done)

    return {"ok": True, "status": "ok", "items": items,
            "closed": len(done), "closedItems": done, **totals}

async def positions(req):
    """GET only — see the Route entry. There is no write path for this data."""
    return JSONResponse(await run(_cached_call, "positions", _positions, 30))


async def fno_pnl(req):
    """The recorded F&O P&L curve. Reads the local record only — it does not
    call the broker, so it still answers with the history after the daily token
    expires, which is exactly when a tracker is worth having."""
    import re as _re
    from services.fno_pnl import history
    # ?from=/&to= are ISO dates. Anything else is ignored rather than passed to
    # the query — these interpolate into a BETWEEN, so the shape is checked here.
    def _date(name: str) -> str | None:
        v = (req.query_params.get(name) or "").strip()
        return v if _re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) else None
    lo, hi = _date("from"), _date("to")
    return JSONResponse({"ok": True, **await run(
        _cached_call_arg, f"fno_pnl_{lo}_{hi}", lambda a: history(*a), (lo, hi), 60)})


async def fno_pnl_backfill(req):
    """Rebuild the daily record from Upstox trade history.

    POST because it writes. It reads the trade *record* and derives P&L from it
    — there is no order path here, same as every other route in this file.
    """
    from services.fno_pnl import backfill
    res = await run(backfill, 3)
    # Every window's cached history is stale the moment this lands.
    for key in [k for k in _cache if k.startswith("fno_pnl_")]:
        _cache.pop(key, None)
    return JSONResponse(res)


# ======================================================================
# Real price history — backs sparklines, the portfolio curve and the risk
# metrics. All of those were previously drawn from lib/data.ts::series(), a
# seeded random walk keyed off the symbol's own letters: the "30D" sparkline
# for a stock never changed, and the portfolio performance chart was a random
# walk seeded with the constant 99. prices_daily already holds real daily
# closes for 3169 symbols, so none of that needed to be synthetic.
# ======================================================================
def _history(symbols: tuple[str, ...], days: int = 30) -> dict[str, list[float]]:
    """Trailing closes per symbol, oldest first. One query, not N."""
    if not symbols:
        return {}
    marks = ",".join("?" * len(symbols))
    with get_connection() as conn:
        rows = conn.execute(f"""
            SELECT symbol, date, close FROM (
                SELECT symbol, date, close,
                       ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC) AS rn
                FROM prices_daily WHERE symbol IN ({marks})
            ) WHERE rn <= ? ORDER BY symbol, date ASC
        """, (*symbols, days)).fetchall()
    out: dict[str, list[float]] = {}
    for r in rows:
        if r["close"] is not None:
            out.setdefault(r["symbol"], []).append(round(float(r["close"]), 2))
    return out


def _candles(symbol: str, days: int) -> list[dict]:
    """Full OHLC bars for one symbol — what a candlestick chart needs."""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT date, open, high, low, close, volume FROM (
                SELECT date, open, high, low, close, volume,
                       ROW_NUMBER() OVER (ORDER BY date DESC) AS rn
                FROM prices_daily WHERE symbol = ? AND close IS NOT NULL
            ) WHERE rn <= ? ORDER BY date ASC
        """, (symbol, days)).fetchall()
    out = []
    for r in rows:
        o, h, l, c = r["open"], r["high"], r["low"], r["close"]
        if None in (o, h, l, c):
            continue
        out.append({"t": r["date"], "open": round(float(o), 2), "high": round(float(h), 2),
                    "low": round(float(l), 2), "close": round(float(c), 2),
                    "volume": int(r["volume"] or 0)})
    return out


async def history(req):
    raw = (req.query_params.get("symbols") or "").strip()
    if not raw:
        return JSONResponse({"ok": True, "series": {}})
    # Cap the fan-out: a table renders at most a screenful of rows.
    symbols = tuple(dict.fromkeys(s.strip().upper() for s in raw.split(",") if s.strip()))[:200]
    # `?symbols=,` is non-empty but parses to nothing — the ohlc branch below
    # indexes [0] and would raise IndexError.
    if not symbols:
        return JSONResponse({"ok": True, "series": {}})
    days = max(2, min(400, int(req.query_params.get("days") or 30)))

    # ohlc=1 returns candlesticks for a single symbol (F&O index chart);
    # the default close-only shape is what table sparklines need.
    if req.query_params.get("ohlc") in ("1", "true"):
        key = f"ohlc:{days}:{symbols[0]}"
        bars = await run(_cached_call_arg, key, _candles_days, (symbols[0], days), 900)
        return JSONResponse({"ok": True, "candles": bars})

    key = f"hist:{days}:{','.join(symbols)}"
    return JSONResponse({"ok": True, "series": await run(_cached_call_arg, key, _history_days, (symbols, days), 900)})


def _history_days(arg):
    symbols, days = arg
    return _history(symbols, days)


def _candles_days(arg):
    symbol, days = arg
    return _candles(symbol, days)


def _portfolio_curve() -> dict:
    """Real portfolio value over time, plus risk metrics from actual returns.

    Value on each date = sum(qty * that date's close) over holdings that have
    history. Everything downstream (volatility, VaR, max drawdown) is computed
    from this real series. The risk page previously hardcoded beta = 1.06,
    VaR = 2.1% of value, and "Max historical DD -14.2%".
    """
    hold = _holdings() or {}
    items = hold.get("items") or []
    if not items:
        return {"ok": True, "points": [], "metrics": {}, "covered": 0, "total": 0}

    qty = {i["symbol"]: i.get("qty") or 0 for i in items if i.get("symbol")}
    hist = _history(tuple(qty), days=250)

    # Only symbols with history can contribute; report the shortfall rather
    # than silently drawing a curve that omits part of the book.
    covered = [s for s in qty if hist.get(s)]
    if not covered:
        return {"ok": True, "points": [], "metrics": {}, "covered": 0, "total": len(qty)}

    with get_connection() as conn:
        marks = ",".join("?" * len(covered))
        rows = conn.execute(f"""
            SELECT symbol, date, close FROM prices_daily
            WHERE symbol IN ({marks}) AND close IS NOT NULL
            ORDER BY date ASC
        """, tuple(covered)).fetchall()

    by_date: dict[str, float] = {}
    seen_per_date: dict[str, int] = {}
    for r in rows:
        d = r["date"]
        by_date[d] = by_date.get(d, 0.0) + float(r["close"]) * qty.get(r["symbol"], 0)
        seen_per_date[d] = seen_per_date.get(d, 0) + 1

    # Drop partial days (a holiday for one symbol would fake a value drop).
    full = len(covered)
    points = [{"t": d, "v": round(v, 2)} for d, v in sorted(by_date.items())
              if seen_per_date.get(d) == full][-250:]

    return {"ok": True, "points": points, "metrics": _risk_metrics(points),
            "covered": len(covered), "total": len(qty)}


def _risk_metrics(points: list[dict]) -> dict:
    """Volatility, historical VaR and max drawdown from the real value series."""
    if len(points) < 20:
        return {}
    vals = [p["v"] for p in points]
    rets = [(vals[i] / vals[i - 1]) - 1 for i in range(1, len(vals)) if vals[i - 1]]
    if len(rets) < 20:
        return {}

    import statistics
    vol_daily = statistics.pstdev(rets)
    # 5th percentile of actual daily returns — historical VaR, not a guess.
    var95_pct = sorted(rets)[max(0, int(len(rets) * 0.05))] * 100

    peak, max_dd = vals[0], 0.0
    for v in vals:
        peak = max(peak, v)
        if peak:
            max_dd = min(max_dd, (v / peak - 1) * 100)

    return {
        "volatilityAnnualPct": round(vol_daily * (252 ** 0.5) * 100, 2),
        "var95Pct": round(var95_pct, 2),
        "var95Value": round(vals[-1] * abs(var95_pct) / 100, 2),
        "maxDrawdownPct": round(max_dd, 2),
        "observations": len(rets),
    }


async def portfolio_curve(req):
    return JSONResponse(await run(_cached_call, "portfolio_curve", _portfolio_curve, 300))


async def ensure_fresh(req):
    """Refresh the symbols the user is actually looking at.

    Called by table/detail pages with the symbols they render. Replaces the
    nightly bulk crawl: data is ingested on view rather than on a cron, so
    coverage follows real usage instead of grinding through thousands of
    symbols nobody opens. Returns immediately — the fetch happens in the
    background and lands for the next render.
    """
    raw = (req.query_params.get("symbols") or "").strip()
    if not raw:
        return JSONResponse({"ok": True, "queued": 0, "stale": 0})
    symbols = [s.strip().upper() for s in raw.split(",") if s.strip()]
    from services.freshness import refresh_async
    return JSONResponse({"ok": True, **refresh_async(symbols)})


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
    # Cached at 5s, not 30s: the Settings page polls this to watch a manual
    # run progress, and a 30s-stale payload makes a job that finished in 4s
    # look stuck.
    return JSONResponse({"ok": True, **await run(_cached_call, "ingestion_status", _ingestion_status, 5)})


async def ingestion_run(req):
    """Trigger one ETL job on demand (Settings page).

    Returns as soon as the job is queued — these run from ~4s (live quotes) to
    several minutes (symbol master), past any reasonable HTTP timeout. The
    caller polls /api/ingestion/status for the outcome.
    """
    try:
        body = await req.json()
    except Exception:
        body = {}
    job_id = (body.get("job_id") or "").strip()
    if not job_id:
        return JSONResponse({"ok": False, "error": "job_id required"}, status_code=400)

    from ingestion.scheduler import trigger_job
    res = await run(trigger_job, job_id)
    _cache.pop("ingestion_status", None)   # so the next poll shows it running
    return JSONResponse(res, status_code=200 if res.get("ok") else 409)


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
    Route("/api/indices", india_board),
    Route("/api/data-health", data_health),
    Route("/api/events", events),
    # Before /api/fno/{index}: Starlette matches in order, and the wildcard
    # would otherwise swallow "pnl" as an index name.
    Route("/api/fno/pnl", fno_pnl, methods=["GET"]),
    Route("/api/fno/pnl/backfill", fno_pnl_backfill, methods=["POST"]),
    Route("/api/fno/{index}", fno),
    Route("/api/fno/{index}/expiries", fno_expiries),
    Route("/api/fno/{index}/term", fno_term),
    Route("/api/fno/{index}/narrative", fno_narrative_route),
    Route("/api/fno/{index}/oi-read", fno_oi_read_route),
    Route("/api/ai", ai, methods=["POST"]),
    Route("/api/ai/stream", ai_stream, methods=["POST"]),
    Route("/api/brief", brief),
    Route("/api/alerts", alerts_list, methods=["GET"]),
    Route("/api/alerts", alerts_create, methods=["POST"]),
    Route("/api/alerts/{id}", alerts_delete, methods=["DELETE"]),
    Route("/api/watchlists", watchlists_list, methods=["GET"]),
    Route("/api/watchlists", watchlists_create, methods=["POST"]),
    Route("/api/watchlists/{id}", watchlists_delete, methods=["DELETE"]),
    Route("/api/watchlists/{id}/items", watchlist_add_symbol, methods=["POST"]),
    Route("/api/watchlists/{id}/items/{symbol}", watchlist_remove_symbol, methods=["DELETE"]),
    Route("/api/holdings", holdings),
    # methods=["GET"] is explicit and load-bearing: this account-scoped route is
    # read-only by design and must reject every write verb with a 405.
    Route("/api/positions", positions, methods=["GET"]),
    Route("/api/history", history),
    Route("/api/ensure", ensure_fresh),
    Route("/api/portfolio/curve", portfolio_curve),
    Route("/api/upstox/status", upstox_status),
    Route("/api/upstox/token", upstox_token, methods=["POST"]),
    Route("/api/system/status", system_status),
    Route("/api/ingestion/status", ingestion_status),
    Route("/api/ingestion/run", ingestion_run, methods=["POST"]),
    # /api/udf/{config,symbols,search,history,time} — the TradingView datafeed.
    *udf_routes,
    WebSocketRoute("/ws", ws_endpoint),
]

def _prewarm_caches() -> None:
    """Populate the slow market-data caches at boot, off the event loop.

    Stale-while-revalidate removes the recurring cost, but the very first
    caller after a restart still pays it (nothing cached to serve). Warming
    on startup means real users never see the 2.5-6.3s cold path at all.
    """
    def warm():
        from services.movers import get_top_movers
        from services.breadth import get_market_pulse
        from services.global_markets import get_global_board, get_india_board
        # _universe is the heaviest DB query in the app (5173 rows joined
        # against per-symbol latest prices) and every page hits it, so it
        # matters most of all here.
        for key, fn, ttl in (
            ("__universe__", _universe, 60),
            # Cold, this one takes ~8s (Upstox + a yfinance fallback pass) —
            # longer than the web route's own timeout, so an unwarmed dashboard
            # renders no ticker at all on the first load after a restart.
            ("india", get_india_board, 20),
            ("movers", get_top_movers, 300),
            ("pulse", get_market_pulse, 180),
            ("global", get_global_board, 300),
        ):
            try:
                fn() if key == "__universe__" else _cached_call(key, fn, ttl)
            except Exception as e:
                logging.getLogger("api.server").warning(f"prewarm {key} failed: {e}")
    _REFRESH_POOL.submit(warm)


def _catch_up_prices() -> None:
    """Backfill any closes missed while the container was down.

    The price cron fires at one exact minute with no misfire grace, so any
    restart spanning that minute skipped the run and nothing ever went back for
    it — that is how 1704 symbols came to sit days behind while the app served
    their stale close as the current price. Runs in the background so boot is
    never blocked on the network; it's a no-op when nothing is behind.
    """
    def work():
        log = logging.getLogger("api.server")
        target = None
        try:
            from ingestion.quotes import catch_up
            res = catch_up()
            target = res.get("target")
            if res.get("symbols"):
                log.info(f"price catch-up: {res}")
                # @cached(60) keys by fn.__name__ + repr(args) — "__universe__"
                # is the prewarm label, never a key that was actually written.
                _cache.pop("_universe()", None)   # stale prices are cached; drop them
        except Exception as e:
            log.warning(f"price catch-up failed: {e}")
        # Index candles ride a separate cron (20:45) and fell behind the same
        # way — the F&O chart then draws its levels above a two-session-old
        # candle and looks broken. Same thread, so boot stays non-blocking.
        try:
            from ingestion import index_history
            log.info(f"index catch-up: {index_history.catch_up(target)}")
        except Exception as e:
            log.warning(f"index catch-up failed: {e}")

    _REFRESH_POOL.submit(work)


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
    try:
        from services.upstox_stream import get_stream_manager
        from services.upstox import INDEX_KEYS
        stream = get_stream_manager()
        stream.on_tick(ws_manager.broadcast_tick)
        stream.start(initial_keys=list(INDEX_KEYS.values()))
    except Exception as e:
        logging.getLogger("api.server").error(f"Upstox market-data stream failed to start: {e}")
    _prewarm_caches()
    _catch_up_prices()
    yield
    try:
        from ingestion.scheduler import stop_scheduler
        stop_scheduler()
    except Exception:
        pass

# The browser never calls this API cross-origin — every page goes through the
# Next.js server-side routes in web/app/api (only /ws is opened directly, and
# WebSockets aren't subject to CORS). `allow_origins=["*"]` therefore bought
# nothing and let any site the user happened to visit read /api/holdings (the
# real portfolio) and POST /api/upstox/token, since there is no auth on these
# routes. Override with ARTHA_CORS_ORIGINS="https://a,https://b" if the UI is
# ever served from another host.
import os as _os
_ORIGINS = [o.strip() for o in
            (_os.getenv("ARTHA_CORS_ORIGINS") or "http://localhost:3000,http://127.0.0.1:3000").split(",")
            if o.strip()]

app = Starlette(
    routes=routes,
    lifespan=_lifespan,
    exception_handlers={Exception: unhandled},
    middleware=[Middleware(CORSMiddleware, allow_origins=_ORIGINS, allow_methods=["*"])],
)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
