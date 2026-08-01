"""
ARTHA Terminal - Tool Registry
Defines all tools available to the LLM agent.
"""

from dataclasses import dataclass
from typing import Callable, Any
import asyncio
import json
import time


@dataclass
class Tool:
    """Tool definition for LLM function calling."""
    name: str
    description: str
    parameters: dict
    handler: Callable


# Tool JSON Schema for OpenRouter/Nvidia API
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_price_history",
            "description": "Get historical OHLCV price data with computed technical indicators",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Stock symbol (e.g., RELIANCE, TCS)"
                    },
                    "start_date": {
                        "type": "string",
                        "format": "date",
                        "description": "Start date (YYYY-MM-DD)"
                    },
                    "end_date": {
                        "type": "string",
                        "format": "date",
                        "description": "End date (YYYY-MM-DD)"
                    },
                    "interval": {
                        "type": "string",
                        "enum": ["1d", "1wk", "1mo"],
                        "description": "Candle interval"
                    }
                },
                "required": ["symbol"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_fundamentals",
            "description": "Get financial ratios, valuation metrics, and key fundamentals",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Stock symbol"
                    }
                },
                "required": ["symbol"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_shareholding",
            "description": "Get quarterly ownership patterns (promoter, FII, DII, public)",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Stock symbol"
                    },
                    "quarters": {
                        "type": "integer",
                        "description": "Number of recent quarters (default: 8)"
                    }
                },
                "required": ["symbol"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "resolve_peers",
            "description": "Get top-N same-industry peers by market cap for comparison",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Stock symbol"
                    },
                    "n": {
                        "type": "integer",
                        "description": "Number of peers (default: 5)",
                        "default": 5
                    }
                },
                "required": ["symbol"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "scan_red_flags",
            "description": "Run deterministic red-flag engine to identify financial risks",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Stock symbol"
                    }
                },
                "required": ["symbol"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "compute_scorecard",
            "description": "Generate weighted 0-10 analysis scorecard (valuation, growth, health, momentum, sector)",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Stock symbol"
                    }
                },
                "required": ["symbol"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "sector_news",
            "description": "Fetch recent news headlines for a sector via search API",
            "parameters": {
                "type": "object",
                "properties": {
                    "sector": {
                        "type": "string",
                        "description": "Sector name (e.g., Banking, IT, Pharma)"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of headlines (default: 10)",
                        "default": 10
                    }
                },
                "required": ["sector"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_market",
            "description": "Search for stocks by name, sector, or criteria",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (company name, sector, industry)"
                    },
                    "limit": {
                        "type": "integer",
                        "default": 10
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_institutional_flows",
            "description": "Market-wide FII/DII net cash flows for the latest published session, with the multi-day trend. Market level, not per-symbol — takes no arguments",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_index_membership",
            "description": "Which NSE indices a symbol belongs to (NIFTY 50, Bank Nifty, sector indices), plus NSE's own industry label",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Stock symbol"
                    }
                },
                "required": ["symbol"]
            }
        }
    }
]


class ToolRegistry:
    """Registry and dispatcher for agent tools."""

    def __init__(self):
        self._tools: dict[str, Callable] = {}
        self._registered = False

    def register(self, func: Callable) -> Callable:
        """Decorator to register a tool."""
        self._tools[func.__name__] = func
        self._registered = True
        return func

    def get_tool(self, name: str) -> Callable | None:
        """Get tool handler by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[Tool]:
        """List all registered tools with schemas."""
        return TOOL_SCHEMAS


# Global registry
registry = ToolRegistry()


# ============================================
# Tool Handlers — backed by the real services/engines, not stubs.
#
# All of these were previously NOT_IMPLEMENTED placeholders even though the
# real data sources already existed in services/engines; the LLM would call
# them mid-analysis and silently get an empty payload back. get_shareholding
# stays NOT_IMPLEMENTED for real: there's no quarterly promoter/FII/DII
# scraper wired up anywhere in the project, so that one's an honest gap.
# ============================================

# Per-symbol live snapshot (yfinance) is the shared input for price history,
# fundamentals, peers, red flags, and the scorecard — one tool call fetching
# it, cached briefly so a single chat turn that calls several of these tools
# for the same symbol doesn't hit yfinance five times over.
_SNAP_TTL = 300  # seconds
_snap_cache: dict[str, tuple[float, dict | None]] = {}


def _get_snapshot(symbol: str) -> dict | None:
    from services.stock_data import get_live_stock_data
    key = symbol.strip().upper()
    hit = _snap_cache.get(key)
    if hit and time.time() - hit[0] < _SNAP_TTL:
        return hit[1]
    snap = get_live_stock_data(key)
    _snap_cache[key] = (time.time(), snap)
    return snap


@registry.register
async def get_price_history(
    symbol: str,
    start_date: str | None = None,
    end_date: str | None = None,
    interval: str = "1d"
) -> dict:
    """Get historical OHLCV price data with computed technical indicators."""
    snap = await asyncio.to_thread(_get_snapshot, symbol)
    if not snap:
        return {"symbol": symbol, "data": [], "status": "NOT_FOUND",
                "message": f"No price history available for {symbol}."}

    df = snap["history"]
    if start_date:
        df = df[df["date"] >= start_date]
    if end_date:
        df = df[df["date"] <= end_date]
    # Cap the payload back to the LLM — it doesn't need 5 years of daily candles.
    rows = df.tail(180).to_dict("records")
    # `data` is ascending (oldest first, most recent last) — free-tier models
    # were observed citing an early/arbitrary row as "latest" instead of
    # scanning to the end of a 180-row array. Surface latest_close/latest_date
    # as explicit top-level fields so there's nothing to infer.
    return {"symbol": symbol, "data": rows, "metrics": snap["metrics"],
            "latest_close": snap.get("latest_close"), "latest_date": snap.get("latest_date"),
            "status": "OK"}


@registry.register
async def get_fundamentals(symbol: str) -> dict:
    """Get financial ratios, valuation metrics, and key fundamentals."""
    snap = await asyncio.to_thread(_get_snapshot, symbol)
    if not snap:
        return {"symbol": symbol, "status": "NOT_FOUND"}
    return {"symbol": symbol, **snap["fundamentals"], "status": "OK"}


@registry.register
async def get_shareholding(symbol: str, quarters: int = 8) -> dict:
    """Get quarterly ownership patterns (promoter, FII, DII, public)."""
    # No quarterly promoter/FII/DII scraper is wired up anywhere in this
    # project (yfinance only exposes a point-in-time institutional-holders
    # snapshot) — this is a genuine data gap, not a stub left unimplemented.
    return {
        "symbol": symbol,
        "data": [],
        "status": "NOT_IMPLEMENTED",
        "message": "No quarterly shareholding-pattern source is configured for this deployment.",
    }


@registry.register
async def resolve_peers(symbol: str, n: int = 5) -> dict:
    """Get top-N same-industry peers by market cap for comparison."""
    snap = await asyncio.to_thread(_get_snapshot, symbol)
    if not snap:
        return {"symbol": symbol, "peers": [], "status": "NOT_FOUND"}
    from services.stock_data import get_sector_peers
    sector = snap["metrics"].get("sector")
    peers_df = await asyncio.to_thread(get_sector_peers, symbol, sector, "return_6m")
    peers = peers_df.to_dict("records") if peers_df is not None and not peers_df.empty else []
    return {"symbol": symbol, "peers": peers[:n], "status": "OK"}


@registry.register
async def scan_red_flags(symbol: str) -> dict:
    """Run deterministic red-flag engine to identify financial risks."""
    snap = await asyncio.to_thread(_get_snapshot, symbol)
    if not snap:
        return {"symbol": symbol, "flags": [], "status": "NOT_FOUND"}
    from engines.red_flags import RedFlagEngine
    findings = RedFlagEngine().scan(
        fundamentals=snap.get("red_flag_inputs", {}),
        shareholding=snap.get("shareholding", []),
        symbol=symbol,
    )
    flags = [{"rule_id": f.rule_id, "name": f.name, "severity": f.severity.value,
              "message": f.message, "actual_value": f.actual_value} for f in findings]
    return {"symbol": symbol, "flags": flags, "status": "OK"}


@registry.register
async def compute_scorecard(symbol: str) -> dict:
    """Generate weighted 0-10 analysis scorecard (valuation, growth, health, momentum, sector)."""
    snap = await asyncio.to_thread(_get_snapshot, symbol)
    if not snap:
        return {"symbol": symbol, "total_score": None, "sub_scores": {}, "status": "NOT_FOUND"}
    from engines.scorecard import ScorecardEngine
    from services.stock_data import get_sector_peers
    sector = snap["metrics"].get("sector")
    peers_df = await asyncio.to_thread(get_sector_peers, symbol, sector, "return_6m")
    peers = peers_df.to_dict("records") if peers_df is not None and not peers_df.empty else []
    scorecard = ScorecardEngine().compute(
        symbol=symbol, data=snap["metrics"], fundamentals=snap["fundamentals"],
        shareholding=snap.get("shareholding", []), peers=peers,
    )
    return {**scorecard.to_dict(), "status": "OK"}


@registry.register
async def sector_news(sector: str, limit: int = 10) -> dict:
    """Fetch recent news headlines for a sector via search API."""
    from services.search import sector_news as _sector_news
    result = await _sector_news(sector, limit)
    return {**result, "status": "OK"}


@registry.register
async def search_market(query: str, limit: int = 10) -> dict:
    """Search for stocks by name, sector, or criteria."""
    from services.instruments import search as _search_instruments
    results = await asyncio.to_thread(_search_instruments, query, limit)
    return {"query": query, "results": results, "status": "OK"}


# The market-wide FII/DII reading is the same for every symbol in a run, and
# fetching it hits NSE (which is flaky enough that the service retries with
# backoff). Share the per-symbol snapshot cache under a reserved key so a loop
# that calls the tool twice pays for one fetch.
_FLOWS_KEY = "__fii_dii__"


def _get_flows() -> dict:
    from services.institutional_flows import get_institutional_snapshot
    hit = _snap_cache.get(_FLOWS_KEY)
    if hit and time.time() - hit[0] < _SNAP_TTL:
        return hit[1] or {}
    snap = get_institutional_snapshot() or {}
    _snap_cache[_FLOWS_KEY] = (time.time(), snap)
    return snap


@registry.register
async def get_institutional_flows() -> dict:
    """Market-wide FII/DII net cash flows for the latest published session."""
    snap = await asyncio.to_thread(_get_flows)
    fii, dii = (snap.get("fii") or {}), (snap.get("dii") or {})
    if fii.get("net") is None and dii.get("net") is None:
        # NSE publishes this once a day and the fetch can fail outright. Say so
        # — an absent reading is not a neutral one.
        return {"available": False, "status": "NOT_FOUND",
                "message": "No FII/DII flow reading is available. State that "
                           "institutional flows are unavailable; do not infer a direction."}
    trend = snap.get("trend") or {}
    return {
        "available": True,
        "date": snap.get("date"),
        "unit": "Rs Cr, net cash market",
        "fii_net": fii.get("net"), "fii_stance": snap.get("fii_key"),
        "dii_net": dii.get("net"), "dii_stance": snap.get("dii_key"),
        # True when the live NSE call failed and this is the last stored reading.
        "stale": snap.get("stale", False),
        "fii_streak_days": trend.get("fii_streak"), "dii_streak_days": trend.get("dii_streak"),
        "fii_sum_10d": trend.get("fii_sum"), "dii_sum_10d": trend.get("dii_sum"),
        "status": "OK",
    }


def _index_rows(symbol: str) -> list[dict]:
    from db import get_connection
    with get_connection() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT index_key, index_name, industry FROM index_members "
            "WHERE symbol = ? ORDER BY index_name",
            (symbol,),
        ).fetchall()]


@registry.register
async def get_index_membership(symbol: str) -> dict:
    """Which NSE indices a symbol belongs to, from the stored constituent pull."""
    sym = symbol.strip().upper()
    rows = await asyncio.to_thread(_index_rows, sym)
    if not rows:
        # Most of the ~5,000-symbol universe is in no index at all — that is a
        # real answer about the stock, not a data gap to paper over.
        return {"symbol": sym, "indices": [], "available": False, "status": "NOT_FOUND",
                "message": f"{sym} is not a constituent of any index stored in ARTHA's "
                           f"database. Say it is in no tracked index; do not name one."}
    industry = next((r["industry"] for r in rows if r.get("industry")), None)
    return {"symbol": sym, "indices": rows, "industry": industry,
            "available": True, "status": "OK"}


def get_tools_for_llm() -> list[dict]:
    """Get tools in format expected by LLM API."""
    return TOOL_SCHEMAS