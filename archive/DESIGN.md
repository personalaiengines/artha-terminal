# ARTHA Terminal - Design Document (v3)

**Based on:** ARTHA Terminal Ground-Up Build Guide (v2)  
**Modified for:** Nvidia NIM / OpenRouter API instead of Anthropic, Alternative to Tavily  
**Date:** 2026-07-15

---

## Executive Summary

ARTHA Terminal is a real-time Indian equities research terminal with live broker integration (Upstox), agentic AI analysis, and a cyberpunk Streamlit frontend. The system is **read-only** (no order placement) to maintain SEBI-compliant "research & education" posture.

### Key Design Decisions

| Original | Modified | Rationale |
|----------|----------|-----------|
| Anthropic SDK | **OpenRouter + Claude models** (primary) with **Nvidia NIM fallback** | OpenRouter provides full Claude tool-use at competitive pricing |
| Tavily API | **SerpAPI** (primary) with **Bing Search fallback** | SerpAPI $5 credit = ~1,000 searches/mo; Bing for overflow |
| Single model | **Hierarchical fallback**: Claude → Gemini Flash → Llama 3.3 | Ensures reliability while managing costs |

---

## 1. System Architecture

### 1.1 Four Runtime Planes

```
┌─────────────────────────────────────────────────────────────────┐
│                      PRESENTATION PLANE                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │   Landing   │  │   Market    │  │    My Portfolio         │    │
│  │  (3D Hero)  │  │  Analysis   │  │    + Stock Deep-Dive    │    │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘  │
│                    Streamlit App (localhost:8501)               │
└───────────────────────────┬─────────────────────────────────────┘
                            │ read-only
┌───────────────────────────▼─────────────────────────────────────┐
│                      AGENT PLANE                                │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  LLM Orchestration (Nvidia NIM / OpenRouter)            │    │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │    │
│  │  │ Tool Router  │  │ Cache Layer  │  │ Telemetry    │   │    │
│  │  └──────────────┘  └──────────────┘  └──────────────┘   │    │
│  └─────────────────────────────────────────────────────────┘    │
└───────────────────────────┬─────────────────────────────────────┘
                            │ tool calls
┌───────────────────────────▼─────────────────────────────────────┐
│                     DATA INGESTION PLANE                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │  Symbol ETL  │  │ Price ETL    │  │Fundamental   │          │
│  │  (cron)      │  │ (cron)       │  │ ETL (cron)   │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
│                    APScheduler (~20:30 IST)                     │
└───────────────────────────┬─────────────────────────────────────┘
                            │ write
┌───────────────────────────▼─────────────────────────────────────┐
│                        DATA STORE                               │
│              SQLite (WAL mode) - Single file                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │ symbol_master│  │ prices_daily │  │ fundamentals │          │
│  │ shareholding │  │ computed_metrics │  │ agent_cache│          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 Verification Membrane (Cross-Source Consensus)

Every price-critical field passes through the verification membrane before UI exposure:

```
                    ┌─────────────┐
                    │  Request  │
                    └──────┬──────┘
                           │
           ┌───────────────┴───────────────┐
           │                               │
    ┌──────▼──────┐                 ┌──────▼──────┐
    │  Upstox API │                 │ Yahoo Finance │
    └──────┬──────┘                 └──────┬──────┘
           │                               │
           └───────────────┬───────────────┘
                           │
                    ┌──────▼──────┐
                    │  Verify    │
                    │  1.5% Rule │
                    └──────┬──────┘
                           │
           ┌───────────────┼───────────────┐
           │               │               │
    ┌──────▼──────┐ ┌──────▼──────┐ ┌──────▼──────┐
    │  VERIFIED   │ │SINGLE_SOURCE│ │  CONFLICT   │
    │  (green)    │ │  (amber)    │ │  (red)      │
    └─────────────┘ └─────────────┘ └─────────────┘
```

---

## 2. Technology Stack

### 2.1 Core Dependencies

| Category | Packages |
|----------|----------|
| **Web/UI** | streamlit, streamlit-searchbox, plotly, streamlit-extras |
| **Data** | pandas, numpy, requests, beautifulsoup4, lxml, yfinance |
| **Broker** | upstox-python-sdk, websockets |
| **Agent** | httpx (for Nvidia NIM / OpenRouter API calls) |
| **Search** | serpapi, serper, or jina-ai-reader (Tavily alternative) |
| **Store** | sqlite3 (WAL mode), sqlite-utils |
| **Jobs** | APScheduler |
| **3D** | st.components.v1.html (Three.js embedded) |
| **Secrets** | python-dotenv |

### 2.2 API Integration Options

#### AI Model Layer (LLM Provider) - Hierarchical Fallback

**Primary Strategy:** OpenRouter with Claude models (full tool-use support) → Fallback to Nvidia NIM

| Priority | Provider | Model | Use Case | Cost |
|----------|----------|-------|----------|------|
| **1** | OpenRouter | `anthropic/claude-3.5-sonnet` | Complex analysis, deep-dives | ~$3/mil tokens |
| **2** | OpenRouter | `anthropic/claude-3.7-sonnet` | Highest accuracy tasks | ~$6/mil tokens |
| **3** | OpenRouter | `google/gemini-flash-1.5` | Routine queries, fast responses | ~$0.075/mil tokens |
| **4** | Nvidia NIM | `meta/llama-3.3-70b-instruct` | Fallback when OpenRouter unavailable | Free tier available |
| **5** | Nvidia NIM | `qwen/qwen-2.5-72b-instruct` | Additional fallback | Free tier available |

**Why OpenRouter + Claude is optimal:**
- OpenRouter routes directly to Anthropic's API (same quality as direct)
- Full function calling / tool-use support identical to Anthropic SDK
- Often 10-20% cheaper than direct Anthropic pricing
- Single API endpoint handles all fallbacks automatically
- Claude 3.5/3.7 Sonnet have best-in-class tool-use reasoning

**Nvidia NIM as fallback (when OpenRouter rate-limited):**
- Nvidia provides free tier credits for NIM endpoints
- Llama 3.3 70B is excellent for tool-use (on par with Claude 3)
- Qwen 2.5 72B has strong function calling capabilities
- Use when primary provider exhausted or errors

**Configuration:**
```env
# ===========================================
# AI Model Hierarchy (Auto-fallback)
# ===========================================

# Primary: OpenRouter (points to Anthropic directly)
OPENROUTER_API_KEY=your_openrouter_key
OPENROUTER_PRIMARY_MODEL=anthropic/claude-3.5-sonnet
OPENROUTER_FALLBACK_MODEL=google/gemini-flash-1.5

# Secondary: Nvidia NIM (when OpenRouter exhausted/errors)
NVIDIA_API_KEY=your_nvidia_key
NVIDIA_FALLBACK_MODEL=meta/llama-3.3-70b-instruct

# Fail-safe: NIM model when all else fails
NVIDIA_BACKUP_MODEL=qwen/qwen-2.5-72b-instruct

# Recommended model choice in code:
AI_PRIMARY=openrouter/claude-3.5-sonnet   # Best tool-use reasoning
AI_FALLBACK_1=openrouter/gemini-flash-1.5  # Cost-effective
AI_FALLBACK_2=nvidia/llama-3.3-70b         # Free tier backup
```

#### Web Search Layer (Tavily Alternative) - SerpAPI Primary

**IMPORTANT:** Tavily and Bing Search APIs have been discontinued in 2025. Here's the updated configuration:

| Service | Status | Free Tier | Reliability | Best For |
|---------|--------|-----------|-------------|----------|
| **SerpAPI** | ✅ Working | **250 searches/mo** | High | Primary search |
| **SearxNG** | ✅ Working | **Unlimited (self-hosted)** | High | Fallback, zero-cost |
| **Jina AI Reader** | ✅ Working | **Unlimited** | High | URL content extraction |

### SerpAPI (Primary - 250 Free Searches/Month)

- **250 free searches/month** via their free tier
- Google + 50+ search engines supported
- Structured JSON output (ideal for tool-use)
- Well-documented, reliable API
- Paid tiers start at $10/mo for 2,500 searches

### Critical: Usage Management

With only **250 searches/month**, we need a smart caching strategy:

```python
# search/cache.py
# Cache search results for 24-48 hours to reduce API calls

Cache TTL:
- Sector news: 24 hours
- Company news: 12 hours
- Red-flag verification: 48 hours
- Peer comparison: 7 days

Estimated monthly usage with caching:
- Fresh searches: ~80-120 (within 250 limit)
- Cache hits: ~200-300 (zero API cost)
- Total covered queries: ~300-400/mo
```

### Self-Hosted SearxNG (Unlimited Fallback)

When SerpAPI quota exhausted:
- Open-source metasearch engine
- Docker deployment (~10 min setup)
- Aggregates from 50+ engines
- **No rate limits, zero cost**

### Usage Estimate for ARTHA (With Caching)

| Usage Type | Raw Searches | After Caching |
|------------|--------------|---------------|
| Sector News (5 sectors × daily) | ~150 | ~45 (3-day cache) |
| Deep-Dive Web Research (10 stocks/mo) | ~100 | ~100 (one-time) |
| Red-Flag Verification | ~50 | ~15 (3-day cache) |
| Ad-hoc / Buffer | ~50 | ~30 |
| **Total** | **~350** | **~190** |

**Conclusion:** With 70-80% caching, 250 searches/month is **sufficient for moderate use**. Heavy users should set up SearxNG fallback.

**Recommended Architecture with Caching:**

```
┌─────────────────────────────────────────────────────────┐
│                 SEARCH LAYER                            │
│  Primary: SerpAPI (250 searches/mo free)               │
│     → Smart caching (24-48 hr TTL for most queries)    │
│     → Exhausted:                                       │
│  Fallback: SearxNG self-hosted (unlimited)             │
│     → URL extraction: Jina AI (unlimited free)         │
└─────────────────────────────────────────────────────────┘
```

```env
# Web Search Configuration (Tavily/Bing discontinued in 2025)
SEARCH_PROVIDER=serpapi
SERPAPI_KEY=your_serpapi_key      # 250 searches/mo FREE
# Fallback: self-hosted SearxNG (unlimited when SerpAPI exhausted)
SEARXNG_URL=http://localhost:8080  # Docker-deployed instance
# URL extraction (unlimited free):
JINA_API_KEY=optional              # Use when needed for URL content
```

### 2.3 Upstox Integration

| Token Type | Validity | Use Case |
|------------|----------|----------|
| Analytics Token | 1 year | Market data, real-time quotes, historical candles |
| Standard Token | Daily (~03:30 IST) | Portfolio holdings (dynamic IP) |

```env
# Upstox Configuration
UPSTOX_ANALYTICS_TOKEN=long-lived_token    # Market data
UPSTOX_CLIENT_ID=standard_app_id           # Portfolio
UPSTOX_CLIENT_SECRET=app_secret            # Token exchange
UPSTOX_ACCESS_TOKEN=daily_token            # Holdings (regenerate daily)
```

### 2.4 Model Recommendations - OpenRouter Primary, Nvidia NIM Fallback

**OpenRouter Models (Primary - Full Claude Tool-Use):**

| Model | Tool-Use Quality | Speed | Cost per 1M tokens | Best For |
|-------|------------------|-------|-------------------|----------|
| `anthropic/claude-3.5-sonnet` | ⭐⭐⭐⭐⭐ | Fast | ~$3 input / ~$15 output | Complex analysis, deep-dives |
| `anthropic/claude-3.7-sonnet` | ⭐⭐⭐⭐⭐+ | Medium | ~$6 input / ~$18 output | Highest accuracy tasks |
| `google/gemini-flash-1.5` | ⭐⭐⭐⭐ | Very Fast | ~$0.075 input / ~$0.3 output | Routine queries, fast responses |
| `meta-llama/llama-3.1-70b-nitro` | ⭐⭐⭐⭐ | Fast | ~$0.6 input / ~$0.8 output | Cost-effective alternative |

**Nvidia NIM Models (Fallback - When OpenRouter Exhausted):**

| Model | Tool-Use Quality | Speed | Free Tier | Best For |
|-------|------------------|-------|-----------|----------|
| `meta/llama-3.3-70b-instruct` | ⭐⭐⭐⭐ | Fast | Yes (limited) | Primary fallback |
| `qwen/qwen-2.5-72b-instruct` | ⭐⭐⭐⭐ | Fast | Yes (limited) | Secondary fallback |
| `nvidia/nemotron-4-340b-instruct` | ⭐⭐⭐⭐+ | Medium | Limited | Complex reasoning |
| `microsoft/phi-3.5-mini` | ⭐⭐⭐ | Very Fast | Yes | Quick tasks, lightweight |

**Model Selection Strategy in Code:**
```python
# agent/model_router.py
class ModelRouter:
    def __init__(self):
        self.primary = "openrouter/claude-3.5-sonnet"
        self.fallback_1 = "openrouter/gemini-flash-1.5"  
        self.fallback_2 = "nvidia/llama-3.3-70b-instruct"
        self.fallback_3 = "nvidia/qwen-2.5-72b-instruct"
    
    async def chat(self, messages, tools):
        # Try each model in sequence until success
        for model in [self.primary, self.fallback_1, self.fallback_2, self.fallback_3]:
            try:
                result = await self._call_model(model, messages, tools)
                return result
            except RateLimitError:
                continue  # Try next model
            except APIError as e:
                log_error(e)
                continue
        raise MaxRetriesExceeded()
```

---

## 3. Data Store Schema

### 3.1 Tables

```sql
-- symbol_master: Typeahead index (~2,200+ instruments)
CREATE TABLE symbol_master (
    symbol TEXT PRIMARY KEY,
    company_name TEXT NOT NULL,
    isin TEXT UNIQUE,
    exchange TEXT CHECK(exchange IN ('NSE', 'BSE')),
    industry TEXT,
    sector TEXT,
    market_cap_cr REAL,
    mcap_rank INTEGER,
    cap_segment TEXT CHECK(cap_segment IN ('Large', 'Mid', 'Small')),
    updated_at TEXT
);

-- prices_daily: OHLCV history (5Y)
CREATE TABLE prices_daily (
    symbol TEXT REFERENCES symbol_master(symbol),
    date TEXT,
    open REAL, high REAL, low REAL, close REAL, volume INTEGER,
    adj_close REAL,
    source TEXT CHECK(source IN ('upstox', 'yahoo')),
    verified_status TEXT CHECK(verified_status IN ('VERIFIED', 'SINGLE_SOURCE', 'CONFLICT')),
    PRIMARY KEY (symbol, date)
);

-- fundamentals: Company financials
CREATE TABLE fundamentals (
    symbol TEXT REFERENCES symbol_master(symbol),
    date_updated TEXT,
    pe_ratio REAL, pb_ratio REAL, dividend_yield REAL,
    roe REAL, roce REAL, roic REAL,
    debt_to_equity REAL, current_ratio REAL,
    sales_cagr_3y REAL, sales_cagr_5y REAL,
    profit_cagr_3y REAL, profit_cagr_5y REAL,
    ocf REAL, pat REAL,
    source TEXT,
    PRIMARY KEY (symbol)
);

-- shareholding: Quarterly ownership
CREATE TABLE shareholding (
    symbol TEXT REFERENCES symbol_master(symbol),
    quarter TEXT,  -- '2024Q4' format
    promoter_share REAL,
    pledged_share REAL,
    fitl_share REAL,  -- FII
    ditl_share REAL,  -- DII
    public_share REAL,
    PRIMARY KEY (symbol, quarter)
);

-- computed_metrics: Derived calculations
CREATE TABLE computed_metrics (
    symbol TEXT PRIMARY KEY REFERENCES symbol_master(symbol),
    dma_50 REAL, dma_200 REAL,
    ath REAL, atl REAL,
    ath_date TEXT, atl_date TEXT,
    return_1d REAL, return_1w REAL, return_1m REAL,
    return_3m REAL, return_6m REAL, return_1y REAL, return_5y REAL,
    price_percentile_5y REAL,
    sector TEXT,
    updated_at TEXT
);

-- agent_cache: Cached AI analysis (6h TTL)
CREATE TABLE agent_cache (
    key TEXT PRIMARY KEY,
    symbol TEXT,
    analysis_type TEXT,  -- 'deep_dive', 'swot', 'verdict'
    content_json TEXT,   -- Serialized LLM output
    cache_at TEXT,
    ttl_hours INTEGER DEFAULT 6
);
```

### 3.2 Indexes

```sql
CREATE INDEX idx_symbol_master_industry ON symbol_master(industry);
CREATE INDEX idx_symbol_master_cap_segment ON symbol_master(cap_segment);
CREATE INDEX idx_symbol_master_mcap_rank ON symbol_master(mcap_rank);
CREATE INDEX idx_prices_daily_date ON prices_daily(date);
CREATE INDEX idx_shareholding_quarter ON shareholding(quarter);
```

---

## 4. Agent Plane Design

### 4.1 Model Abstraction Layer

```python
# agent/llm_client.py
from abc import ABC, abstractmethod
import httpx
import os

class LLMClient(ABC):
    @abstractmethod
    async def chat(self, messages: list, tools: list = None) -> dict:
        pass
    
    @abstractmethod
    async def tool_use_loop(self, messages: list, tools: list) -> dict:
        """Iterative tool call / result cycling"""
        pass

class NvidiaNIMClient(LLMClient):
    def __init__(self):
        self.base_url = "https://integrate.api.nvidia.com/v1/chat/completions"
        self.api_key = os.getenv("NVIDIA_API_KEY")
        self.model = os.getenv("NVIDIA_MODEL", "meta/llama-3.1-70b-instruct")
    
    async def chat(self, messages, tools=None):
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Accept": "application/json"
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "tools": tools,
                    "tool_choice": "auto" if tools else None
                },
                timeout=60.0
            )
            return response.json()

class OpenRouterClient(LLMClient):
    def __init__(self):
        self.base_url = "https://openrouter.ai/api/v1/chat/completions"
        self.api_key = os.getenv("OPENROUTER_API_KEY")
        self.model = os.getenv("OPENROUTER_MODEL", "google/gemini-flash-1.5")
    
    async def chat(self, messages, tools=None):
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "HTTP-Referer": "https://artha.local",
                    "X-Title": "ARTHA Terminal"
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "tools": tools
                },
                timeout=60.0
            )
            return response.json()
```

### 4.2 Tool Registry

```python
# agent/tools.py
from dataclasses import dataclass
from typing import Callable, Any

@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    handler: Callable

TOOL_MANIFEST = [
    Tool(
        name="get_price_history",
        description="Get historical OHLCV data with computed metrics",
        parameters={
            "symbol": {"type": "string", "description": "Stock symbol"},
            "start_date": {"type": "string", "format": "date"},
            "end_date": {"type": "string", "format": "date"}
        },
        handler=get_price_history  # Pure Python, cached
    ),
    Tool(
        name="get_fundamentals",
        description="Get financial ratios and CAGRs",
        parameters={
            "symbol": {"type": "string"}
        },
        handler=get_fundamentals
    ),
    Tool(
        name="get_shareholding",
        description="Get ownership series + QoQ deltas",
        parameters={
            "symbol": {"type": "string"}
        },
        handler=get_shareholding
    ),
    Tool(
        name="resolve_peers",
        description="Get top-N same-industry peers by market cap",
        parameters={
            "symbol": {"type": "string"},
            "n": {"type": "integer", "default": 5}
        },
        handler=resolve_peers
    ),
    Tool(
        name="scan_red_flags",
        description="Run deterministic red-flag engine",
        parameters={
            "symbol": {"type": "string"}
        },
        handler=scan_red_flags  # Pure Python, deterministic
    ),
    Tool(
        name="compute_scorecard",
        description="Generate 0-10 weighted analysis scorecard",
        parameters={
            "symbol": {"type": "string"}
        },
        handler=compute_scorecard  # Pure Python, deterministic
    ),
    Tool(
        name="sector_news",
        description="Fetch domain-filtered recent headlines via search API",
        parameters={
            "sector": {"type": "string"},
            "limit": {"type": "integer", "default": 10}
        },
        handler=sector_news  # Uses Serper/Jina
    )
]
```

### 4.3 System Prompt (Citation-Constrained)

```
You are an equity research analyst for ARTHA Terminal. Your job: analyze data from tools and produce grounded, sourced observations.

RULES:
1. NEVER emit a number without calling a tool first. If data is missing, say "data unavailable".
2. Every analytical bullet MUST carry a source annotation: [Source: get_fundamentals]
3. You may only reference tool-returned values. No external knowledge.
4. The deterministic engines (scan_red_flags, compute_scorecard) produce auditable outputs.
   Present them faithfully; you cannot override them.
5. Frame all output as "observations for research purposes", NOT "recommendations".

OUTPUT FORMAT:
- SWOT Analysis: 3-5 bullets per quadrant, each with source
- Verdict: Explain why/why-not based on scorecard sub-scores
- Risk factors: List flagged items with severity
```

---

## 5. Deterministic Engines

### 5.1 Red-Flag Engine

```python
# engines/red_flags.py
from dataclasses import dataclass
from enum import Enum

class Severity(Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    NA = "na"  # Insufficient data

@dataclass
class RedFlag:
    name: str
    severity: Severity
    message: str
    rule_id: str

RULES = {
    "PLEDGE_HIGH": {
        "name": "High Promoter Pledge",
        "threshold": 20,  # percent
        "eval": lambda d: (Severity.FAIL if d["pledge"] > 20 else
                          (Severity.PASS if d["pledge"] == 0 else
                           (Severity.WARN if d["pledge"] > 10 else Severity.PASS))),
        "message": "Promoter pledge exceeds safe threshold"
    },
    "OCF_PAT_DIVERGENCE": {
        "name": "OCF vs PAT Mismatch",
        "eval": lambda d: (Severity.FAIL if d["ocf"] < 0 and d["pat"] > 0 else Severity.PASS),
        "message": "Positive PAT but negative operating cash flow"
    },
    "RECEIVABLES_SPIKE": {
        "name": "Receivables Growth Surge",
        "eval": lambda d: (Severity.WARN if d["recv_growth"] > 1.5 * d["rev_growth"] else Severity.PASS),
        "message": "Receivables growing faster than revenue"
    },
    "HIGH_DE": {
        "name": "High Debt-to-Equity",
        "threshold": 2.0,
        "eval": lambda d: (Severity.FAIL if d["de_ratio"] > 2 and d["sector"] not in ["BFSI", "Real Estate"] else Severity.PASS),
        "message": "Elevated leverage for non-BFSI sector"
    },
    "INTEREST_COVERAGE_LOW": {
        "name": "Low Interest Coverage",
        "threshold": 2,
        "eval": lambda d: (Severity.WARN if d["interest_coverage"] < 2 else Severity.PASS),
        "message": "Weak interest coverage ratio"
    },
    "PROMOTER_DECLINE": {
        "name": "Declining Promoter Holding",
        "eval": lambda d: (Severity.WARN if d["promoter_decline_streak"] >= 3 else Severity.PASS),
        "message": "Promoter holding declining for 3+ consecutive quarters"
    }
}

def scan_red_flags(fundamentals: dict, shareholding: list) -> list[RedFlag]:
    """Pure Python - deterministic, auditable, reproducible"""
    flags = []
    for rule_id, rule in RULES.items():
        result = rule["eval"](fundamentals | {"pledge": shareholding[0].pledge if shareholding else 0})
        if result != Severity.PASS:
            flags.append(RedFlag(
                name=rule["name"],
                severity=result,
                message=rule["message"],
                rule_id=rule_id
            ))
    return flags
```

### 5.2 Scorecard Engine

```python
# engines/scorecard.py
from dataclasses import dataclass

@dataclass
class SubScore:
    name: str
    weight: float  # 0-1
    score: float   # 0-10
    factors: dict

def compute_scorecard(symbol: str) -> str:
    """
    Five weighted sub-scores (0-10 scale):
    - Valuation (25%): Inverse P/E percentile vs own 5Y + peer z-score
    - Growth (25%): Blended sales + profit CAGR
    - Financial Health (20%): ROE / D-E / coverage / OCF composite
    - Momentum (15%): vs 200DMA + 6M return percentile
    - Sector Tailwind (15%): Peer median 6M return
    
    Red-flag penalty: -0.5/WARN, -1.0/FAIL (post-weighting)
    Clamp to [0, 10].
    """
    # Pure Python compute - LLM only presents result
    data = load_symbol_data(symbol)
    
    valuation = compute_valuation_score(data)
    growth = compute_growth_score(data)
    health = compute_health_score(data)
    momentum = compute_momentum_score(data)
    sector = compute_sector_score(data)
    
    raw = (
        valuation * 0.25 +
        growth * 0.25 +
        health * 0.20 +
        momentum * 0.15 +
        sector * 0.15
    )
    
    red_flags = scan_red_flags(data.fundamentals, data.shareholding)
    penalty = sum(0.5 if f.severity == Severity.WARN else 1.0 for f in red_flags)
    
    final = max(0, min(10, raw - penalty))
    
    return {
        "total": round(final, 2),
        "sub_scores": {
            "valuation": {"score": valuation, "weight": 0.25},
            "growth": {"score": growth, "weight": 0.25},
            "health": {"score": health, "weight": 0.20},
            "momentum": {"score": momentum, "weight": 0.15},
            "sector": {"score": sector, "weight": 0.15},
        },
        "red_flag_penalty": penalty,
        "red_flags": red_flags
    }
```

---

## 6. Presentation Plane (Streamlit UI)

### 6.1 Design System (Cyberpunk / Gamified)

**Palette:**
```css
:root {
    --abyss: #070B1A;      /* Background */
    --depth: #0E1631;      /* Panels */
    --grid: #1B2A55;       /* Borders */
    --laser: #FF2E86;      /* Primary Neon */
    --surge: #21F3A0;      /* Up/Bull */
    --flare: #FF3B4E;      /* Down/Bear */
    --volt: #FFD84D;       /* Warn/Volatility */
    --frost: #EAF0FF;      /* Text */
    --haze: #7C8BB8;       /* Muted */
}
```

**Typography:**
- Display: Chakra Petch / Michroma
- Data: JetBrains Mono
- Labels: Space Grotesk

**Motion Guidelines:**
- Count-up animations for numbers
- Neon pulse on state changes
- Floating percentage particles
- Reveal-with-glow effects
- Respects `prefers-reduced-motion`

### 6.2 Page Routes

#### Page 1: Landing (Home)
- **Bull-vs-Bear Three.js Hero** - 3D models facing, alternating green/red dominance
- **Index Ribbon** - Nifty 50, Bank Nifty live values
- **Candle Strip** - Ambient animated candlestick band
- **Entry Cards** - Links to Market Analysis / My Portfolio with hover neon sweep

#### Page 2: Market Analysis
- **Market Overview** - Indices, count-up animations
- **Top Gainers/Losers** - Floating % particles (green up / red down)
- **Top Movers by Volume** - Table with volume bars
- **Volatility Radar** - Oscillating viz for highest volatility stocks
- **Live News** - Sector headlines via search API with timestamp chips
- **Trading Strategies** - Educational concepts only (SEBI-safe framing)

#### Page 3: My Portfolio  
- **Summary Panel** - Invested / Current / Day P&L / Total P&L (count-up)
- **Holdings Table** - Glow by P&L sign (green/red)
- **Allocation Wheel** - Revolving arc chart, arc length = % of book, color = P&L status
- **Concentration & Risk** - Largest position, sector overexposure
- **Portfolio Health Score** - Aggregated scorecard (0-10) across all holdings
- **Decisions Panel** - Soft signals (HOLD/WATCH/REVIEW) with cited rationale
- **Persistent SEBI Disclaimer**

#### Page 4: Stock Deep-Dive
- **Typeahead Search** - Local lookup (zero API calls)
- **Identity Panel** - Verified price with provenance status
- **Price 5Y Chart** - Candles + 50/200 DMA + ATH/ATL markers
- **Key Metrics Grid** - Valuation, profitability, leverage ratios
- **Peers Comparison** - Same-industry normalized returns + ratio table
- **Ownership Chart** - 8Q stacked area (Promoter/FII/DII/Public)
- **Red Flags** - Rules diagnostic with severity indicators
- **SWOT Analysis** - Source-chipped LLM bullets
- **Sector Radar** - Grounded outlook via search
- **Verdict Panel** - Score gauge (0-10) + sub-bars + why/why-not
- **Agent Console Side-Rail** - Streamed tool call telemetry

#### Page 5: Demo Mode
- Frozen-snapshot replay of scripted scenarios
- Full run demonstration, red-flag alarm, bull-vs-bear debate
- Market crash simulation, source-conflict demo
- Decoupled from live data (artificial latency)

### 6.3 Global Components

```python
# Global CSS injection
SEO_STYLES = """
<style>
    /* Suppress Streamlit chrome */
    #MainMenu {visibility: hidden;}
    header {visibility: hidden;}
    footer {visibility: hidden;}
    
    /* Cyberpunk base */
    .stApp {
        background-color: var(--abyss);
        color: var(--frost);
        font-family: 'Chakra Petch', sans-serif;
    }
    
    /* Panel styling */
    .panel {
        background: var(--depth);
        border: 1px solid var(--grid);
        border-radius: 8px;
        padding: 1rem;
        box-shadow: 0 0 10px rgba(255, 46, 134, 0.1);
    }
    
    /* Neon accents */
    .neon-border.surge {
        border-color: var(--surge);
        box-shadow: 0 0 15px var(--surge);
    }
    .neon-border.flare {
        border-color: var(--flare);
        box-shadow: 0 0 15px var(--flare);
    }
    
    /* Count-up animation */
    @keyframes countUp {
        from { opacity: 0; transform: translateY(-10px); }
        to { opacity: 1; transform: translateY(0); }
    }
    .count-up {
        animation: countUp 0.5s ease-out;
    }
</style>
"""
```

---

## 7. Caching Strategy

| Cache Type | Scope | TTL | Purpose |
|------------|-------|-----|---------|
| `@st.cache_data` | Streamlit global | Session | symbol_master, prices, metrics |
| Agent cache | SQLite `agent_cache` | 6 hours | Deep-dive LLM output |
| LTP cache | In-memory | 5 seconds | Live quote refresh |
| Demo snapshots | Static JSON | N/A | Committed to repo |

---

## 8. Build Sequence

### Phase 1: Foundation (Days 1-2)
1. [ ] Provision Python 3.11+ virtualenv (uv or venv)
2. [ ] Set up .env with all API keys (Nvidia/OpenRouter, Serper, Upstox)
3. [ ] Validate Upstox connectivity (market quotes + holdings smoke test)
4. [ ] Install dependencies via lockfile

### Phase 2: Data Layer (Days 3-4)
1. [ ] Create SQLite DB with WAL mode
2. [ ] Implement schema migration scripts
3. [ ] Build symbol ETL (NSE/BSE archive + Screener.in)
4. [ ] Build price ETL (Upstox primary, Yahoo backfill)
5. [ ] Build fundamentals ETL (Screener.in scraping)
6. [ ] Set up APScheduler for nightly runs

### Phase 3: Verification & Engines (Days 5-6)
1. [ ] Implement verification membrane (Upstox + Yahoo consensus)
2. [ ] Build red-flag engine with unit tests for determinism
3. [ ] Build scorecard engine with unit tests
4. [ ] Verify both engines produce identical output for same input

### Phase 4: Agent Layer (Days 7-8)
1. [ ] Implement LLM client abstraction (Nvidia NIM / OpenRouter)
2. [ ] Register all tools with schema
3. [ ] Build tool-use loop with telemetry streaming
4. [ ] Wire citation-constrained system prompt
5. [ ] Test agent deep-dive flow end-to-end

### Phase 5: UI Implementation (Days 9-12)
1. [ ] Set up Streamlit multi-page structure
2. [ ] Apply design system (global CSS, fonts, colors)
3. [ ] Build Landing page (Three.js 3D hero embedded)
4. [ ] Build Market Analysis page (live charts, gainers/losers)
5. [ ] Build My Portfolio page (Holdings, allocation wheel, health score)
6. [ ] Build Stock Deep-Dive page (all panels, agent console)
7. [ ] Build Demo Mode (frozen snapshots)

### Phase 6: Polish & Compliance (Days 13-14)
1. [ ] Add SEBI disclaimers to all analytical views
2. [ ] Implement reduced-motion support
3. [ ] Add error boundary states (401 token expiry, API failures)
4. [ ] Performance optimization (cache audits, load times <100ms)
5. [ ] Demo scenario filming prep

---

## 9. API Keys & Secrets Summary

```env
# ===========================================
# ARTHA Terminal - Configuration (v5)
# ===========================================

# AI Model Hierarchy (auto-fallback)
# Primary: OpenRouter with Claude (best tool-use)
OPENROUTER_API_KEY=your_openrouter_key
OPENROUTER_PRIMARY=anthropic/claude-3.5-sonnet
OPENROUTER_FALLBACK=google/gemini-flash-1.5

# Fallback: Nvidia NIM (when OpenRouter exhausted)
NVIDIA_API_KEY=your_nvidia_key
NVIDIA_FALLBACK=meta/llama-3.3-70b-instruct
NVIDIA_BACKUP=qwen/qwen-2.5-72b-instruct

# Search: SerpAPI (250/mo free) + SearxNG fallback (unlimited)
SERPAPI_KEY=your_serpapi_key        # 250 searches/mo FREE
SEARXNG_URL=http://localhost:8080   # Docker SearxNG instance (fallback)

# Upstox Broker Integration
UPSTOX_ANALYTICS_TOKEN=your_analytics_token_1yr_validity
UPSTOX_CLIENT_ID=your_standard_app_id
UPSTOX_CLIENT_SECRET=your_app_secret
UPSTOX_ACCESS_TOKEN=your_daily_token_refreshes_330_IST

# App Configuration
PYTHONUNBUFFERED=1
STREAMLIT_SERVER_PORT=8501
```

---

## 10. Compliance & Safety Boundaries

| Constraint | Implementation |
|------------|----------------|
| Read-only broker | Order APIs NEVER wired (architectural) |
| SEBI disclaimer | Persistent on every analytical + portfolio view |
| Soft signals only | HOLD/WATCH/REVIEW (never buy/sell), always with cited rationale |
| No PII | Session-scoped portfolio; local DB only |
| LLM containment | Citation-constrained prompts + deterministic engines |
| Source provenance | Every price field shows verification status (green/amber/red) |

**SEBI Disclaimer Text:**
```
ARTHA Terminal is for research and educational purposes only. 
The Analysis Score (0-10) is NOT a buy/sell recommendation. 
All data is sourced from public APIs and disclosures. 
Consult a SEBI-registered investment advisor before making investment decisions.
```

---

## 11. Project Structure

```
artha-terminal/
├── .env                    # Secrets (gitignored)
├── requirements.txt        # Dependencies
├── config.py               # Configuration loader
├── main.py                 # Entry point (streamlit run main.py)
│
├── db/
│   ├── schema.sql          # Table definitions
│   ├── migrations/         # Versioned migrations
│   └── artha.db            # SQLite database (gitignored)
│
├── ingestion/
│   ├── __init__.py
│   ├── scheduler.py        # APScheduler setup
│   ├── symbol_etl.py       # NSE/BSE archive pull
│   ├── price_etl.py        # Upstox/Yahoo candle pull
│   └── fundamentals_etl.py # Screener.in scrape
│
├── engines/
│   ├── __init__.py
│   ├── red_flags.py        # Deterministic red-flag rules
│   ├── scorecard.py        # Weighted scoring engine
│   └── verification.py     # Cross-source membrane
│
├── agent/
│   ├── __init__.py
│   ├── llm_client.py       # Nvidia/OpenRouter adapter
│   ├── tools.py            # Tool registry & handlers
│   ├── orchestration.py    # Tool-use loop
│   └── prompts.py          # Citation-constrained system prompt
│
├── services/
│   ├── upstox.py           # Broker API client
│   ├── yahoo.py            # Yahoo Finance fallback
│   ├── search.py           # SerpAPI/SearxNG abstraction
│   └── screener.py         # Fundamentals scraper
│
├── ui/
│   ├── pages/
│   │   ├── 1_Market_Analysis.py
│   │   ├── 2_My_Portfolio.py
│   │   └── 3_Stock_Deep_Dive.py
│   ├── components/
│   │   ├── threejs/        # Three.js 3D hero components
│   │   ├── charts.py       # Plotly chart helpers
│   │   ├── gauges.py       # Score gauge component
│   │   └── news_ticker.py  # Live news ticker
│   ├── theme.py            # Global CSS injection
│   └── utils.py            # Reusable UI helpers
│
├── demo/
│   ├── snapshots.json      # Frozen demo scenarios
│   └── demo_mode.py        # Paced replay engine
│
└── tests/
    ├── test_red_flags.py   # Determinism tests
    ├── test_scorecard.py   # Score computation tests
    ├── test_verification.py # Consensus tests
    └── fixtures/           # Test data
```

---

## 12. Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Upstox token expires (daily) | Auto-regeneration flow via OAuth; alert UI with clear "regenerate" button |
| API rate limits | Batch requests; interval-based caching; exponential backoff |
| LLM hallucination | Citation-constrained prompts; tool-returned values only |
| Database corruption | WAL mode; regular backups; read-only queries from UI |
| 3D performance drop | Graceful fallback to static canvas; reduced-motion-aware |
| Demo mode on camera failure | Isolated demo process; never fails live |

---

## 13. Future Enhancements (Post-v2)

- [ ] PostgreSQL migration for multi-instance deployment
- [ ] WebSocket real-time quotes (Upstox streaming API)
- [ ] Backtesting module (strategy paper-trading)
- [ ] Mobile responsive redesign
- [ ] Multi-portfolio compare
- [ ] Options chain visualization (Indian derivatives)
- [ ] Screener custom query builder

---

## 14. API Provider Comparison

### Nvidia NIM Models (Recommended)

| Model | Strengths | Best For |
|-------|-----------|----------|
| `meta/llama-3.1-70b-instruct` | Best overall reasoning, strong tool-use | Primary agent work |
| `meta/llama-3.3-70b-instruct` | Latest Llama, improved accuracy | Complex analysis |
| `qwen/qwen-2.5-72b-instruct` | Strong multilingual, good math | Data-heavy analysis |
| `microsoft/phi-3.5-mini` | Fast, lightweight | Quick responses |
| `nvidia/nemotron-4-340b-instruct` | Nvidia's own, very capable | Complex reasoning |

### OpenRouter Models (Alternative)

| Model | Strengths | Best For |
|-------|-----------|----------|
| `google/gemini-flash-1.5` | Fast, cheap, good quality | Daily operations |
| `anthropic/claude-3.5-sonnet` | Top-tier reasoning | Complex tasks |
| `meta-llama/llama-3.1-70b-nitro` | Llama via OpenRouter | Cost-effective |

### Search Provider Comparison (2025 - Updated)

| Provider | Status | Free Tier | Cost After | Recommendation |
|----------|--------|-----------|------------|----------------|
| **Tavily** | ❌ Discontinued | Was 1,000/mo | N/A | Avoid - shut down |
| **Bing Search** | ❌ Discontinued | Was 2,000/mo | N/A | Avoid - sunset 2025 |
| **Serper.dev** | ✅ Working | 5,000/mo | $0.01/search | Alternative option |
| **SerpAPI** | ✅ **WORKING** | **250/mo** | $10/1,000 | **Primary (your choice)** |
| **SearxNG** | ✅ Working | **Unlimited** | Free (self-hosted) | **Fallback when exhausted** |
| **Jina AI** | ✅ Working | Unlimited | Free | URL extraction only |

**Final Configuration for ARTHA Terminal:**

```
Primary: SerpAPI (250 searches/mo free)
   → With smart caching (70-80% cache hit rate)
   → Exhausted:
Fallback: SearxNG self-hosted via Docker (unlimited, zero cost)
URL Extract: Jina AI Reader (free, unlimited)
```

**Caching Strategy for 250 Searches/Month:**
- Sector news: 72-hour cache (reduces 150→45 searches)
- Company news: 24-hour cache
- Red-flag verification: 48-hour cache
- Peer comparisons: 7-day cache

**Result:** ~190 fresh searches/month needed → **Fits within 250 free tier**

---

## 15. ✅ Design Approval Checklist

Review the following before greenlighting dev:

- [ ] AI provider chosen: OpenRouter (Claude) with Nvidia NIM fallback
- [ ] Search provider chosen: SerpAPI (250/mo free) + SearxNG fallback
- [ ] Caching strategy implemented (to extend 250 searches)
- [ ] All API keys provisioned and tested
- [ ] Upstox Analytics token regenerated
- [ ] Design system colors reviewed (cyberpunk neon palette)
- [ ] SEBI compliance language verified
- [ ] Build sequence approved (14-day timeline)
- [ ] Demo mode scenarios finalized

---

**Design Document v3 - End**