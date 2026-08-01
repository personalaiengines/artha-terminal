-- ============================================
-- ARTHA Terminal - Database Schema
-- SQLite with WAL mode enabled
-- ============================================

-- Enable WAL mode for concurrent reads/writes
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA cache_size = 10000;
PRAGMA temp_store = MEMORY;

-- ============================================
-- Table: symbol_master
-- Typeahead index (~2,200+ instruments)
-- ============================================
CREATE TABLE IF NOT EXISTS symbol_master (
    symbol TEXT PRIMARY KEY,
    company_name TEXT NOT NULL,
    isin TEXT UNIQUE,
    exchange TEXT CHECK(exchange IN ('NSE', 'BSE')) NOT NULL,
    industry TEXT,
    sector TEXT,
    market_cap_cr REAL,
    mcap_rank INTEGER,
    cap_segment TEXT CHECK(cap_segment IN ('Large', 'Mid', 'Small', 'Other')),
    listing_date TEXT,
    symbol_aliases TEXT,  -- JSON array of alternative symbols
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- ============================================
-- Table: prices_daily
-- OHLCV history (5Y daily candles)
-- ============================================
CREATE TABLE IF NOT EXISTS prices_daily (
    symbol TEXT NOT NULL REFERENCES symbol_master(symbol),
    date TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume INTEGER,
    adj_close REAL,
    source TEXT CHECK(source IN ('upstox', 'yahoo', 'nse', 'bse')) DEFAULT 'upstox',
    verified_status TEXT CHECK(verified_status IN ('VERIFIED', 'SINGLE_SOURCE', 'CONFLICT', 'PENDING')) DEFAULT 'SINGLE_SOURCE',
    upstox_ltp REAL,  -- Parallel source for verification
    yahoo_ltp REAL,   -- Parallel source for verification
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (symbol, date)
);

-- ============================================
-- Table: prices_intraday
-- 1-MINUTE bars only. Coarser resolutions (5m/15m/1h) are resampled from these
-- at read time in services/intraday.py — Upstox hard-rejects those intervals
-- (HTTP 400 UDAPI1020: "Interval accepts one of (1minute,30minute,day,week,
-- month)"), so they can never be fetched, only computed.
--
-- `ts` is Unix SECONDS, UTC, and is the bar's OPEN time.
-- No FK to symbol_master on purpose: the F&O indices (NIFTY/BANKNIFTY/SENSEX)
-- are not instruments in symbol_master, and a FK would reject every row.
-- ============================================
CREATE TABLE IF NOT EXISTS prices_intraday (
    symbol TEXT NOT NULL,
    ts INTEGER NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume INTEGER,
    PRIMARY KEY (symbol, ts)
);
CREATE INDEX IF NOT EXISTS idx_intraday_symbol_ts ON prices_intraday(symbol, ts);

-- ============================================
-- Table: fii_dii_flows
-- Daily FII/DII net cash-market flows (NSE), accumulated for trend
-- ============================================
CREATE TABLE IF NOT EXISTS fii_dii_flows (
    date TEXT PRIMARY KEY,
    fii_net REAL,
    dii_net REAL,
    fii_buy REAL,
    fii_sell REAL,
    dii_buy REAL,
    dii_sell REAL,
    created_at TEXT DEFAULT (datetime('now'))
);

-- ============================================
-- Table: fundamentals
-- Company financial ratios and metrics
-- ============================================
CREATE TABLE IF NOT EXISTS fundamentals (
    symbol TEXT NOT NULL REFERENCES symbol_master(symbol),
    date_updated TEXT NOT NULL,

    -- Valuation Ratios
    pe_ratio REAL,
    pb_ratio REAL,
    ps_ratio REAL,
    ev_ebitda REAL,
    dividend_yield REAL,

    -- Profitability Ratios
    roe REAL,
    roce REAL,
    roic REAL,
    gross_margin REAL,
    operating_margin REAL,
    net_margin REAL,

    -- Leverage Ratios
    debt_to_equity REAL,
    current_ratio REAL,
    quick_ratio REAL,
    interest_coverage REAL,

    -- Growth Rates
    sales_cagr_3y REAL,
    sales_cagr_5y REAL,
    profit_cagr_3y REAL,
    profit_cagr_5y REAL,

    -- Cash Flow
    ocf_ttm REAL,
    fcf_ttm REAL,
    ocf_to_pat REAL,

    -- Other
    pat_ttm REAL,
    revenue_ttm REAL,
    book_value REAL,
    canvassing_expense REAL,

    source TEXT DEFAULT 'screener',
    created_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (symbol)
);

-- ============================================
-- Table: shareholding
-- Quarterly ownership patterns
-- ============================================
CREATE TABLE IF NOT EXISTS shareholding (
    symbol TEXT NOT NULL REFERENCES symbol_master(symbol),
    quarter TEXT NOT NULL,  -- Format: '2024Q4'

    -- Shareholder Percentages
    promoter_share REAL,
    pledged_share REAL,
    fitl_share REAL,   -- Foreign Institutional Investors
    ditl_share REAL,   -- Domestic Institutional Investors
    public_share REAL,
    other_share REAL,

    -- Quarter-over-Quarter Changes
    promoter_qoq REAL,
    fii_qoq REAL,
    din_qoq REAL,
    public_qoq REAL,

    source TEXT DEFAULT 'screener',
    created_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (symbol, quarter)
);

-- ============================================
-- Table: computed_metrics
-- Derived calculations and technical indicators
-- ============================================
CREATE TABLE IF NOT EXISTS computed_metrics (
    symbol TEXT PRIMARY KEY REFERENCES symbol_master(symbol),

    -- Technical Indicators
    dma_50 REAL,
    dma_200 REAL,
    rsi_14 REAL,
    beta REAL,

    -- All Time High/Low
    ath REAL,
    atl REAL,
    ath_date TEXT,
    atl_date TEXT,
    distance_from_ath REAL,  -- Percentage
    distance_from_atl REAL,  -- Percentage

    -- Returns (Percentage)
    return_1d REAL,
    return_1w REAL,
    return_1m REAL,
    return_3m REAL,
    return_6m REAL,
    return_1y REAL,
    return_3y REAL,
    return_5y REAL,

    -- Percentiles (vs own 5Y history)
    price_percentile_5y REAL,
    pe_percentile_5y REAL,
    pb_percentile_5y REAL,

    -- Market Cap Classification
    market_cap_rank INTEGER,
    sector TEXT,
    industry TEXT,
    cap_segment TEXT,

    -- Analysis Score (from scorecard engine)
    analysis_score REAL,  -- 0-10 scale

    last_calculated TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- ============================================
-- Table: agent_cache
-- Cached AI analysis outputs (6-hour TTL)
-- ============================================
CREATE TABLE IF NOT EXISTS agent_cache (
    key TEXT PRIMARY KEY,
    symbol TEXT NOT NULL REFERENCES symbol_master(symbol),
    analysis_type TEXT CHECK(analysis_type IN ('deep_dive', 'swot', 'verdict', 'sector_outlook', 'red_flags', 'market_news')) NOT NULL,
    content_json TEXT NOT NULL,  -- Serialized LLM output
    model_used TEXT,
    tokens_used INTEGER,
    cache_at TEXT NOT NULL,
    ttl_hours INTEGER DEFAULT 6,
    expires_at TEXT NOT NULL,

    -- Debug/Metadata
    prompt_hash TEXT,
    tool_calls JSON,

    created_at TEXT DEFAULT (datetime('now'))
);

-- ============================================
-- Table: search_cache
-- Cached search results (24-72 hour TTL)
-- ============================================
CREATE TABLE IF NOT EXISTS search_cache (
    key TEXT PRIMARY KEY,  -- Hash of query + sector
    query TEXT NOT NULL,
    sector TEXT,
    symbol TEXT,
    results_json TEXT NOT NULL,
    source TEXT CHECK(source IN ('serpapi', 'searxng', 'jina', 'finnhub')) NOT NULL,
    cache_at TEXT NOT NULL,
    ttl_hours INTEGER NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

-- ============================================
-- Table: audit_log
-- System events and API usage tracking
-- ============================================
-- Ingestion job run history — powers the Alerts-page ingestion monitor
-- (last run, status, stats) and lets the API compute "next run" without a
-- live scheduler process.
CREATE TABLE IF NOT EXISTS ingestion_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT CHECK(status IN ('running', 'success', 'error')) NOT NULL DEFAULT 'running',
    stats_json TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_ingestion_runs_job_started ON ingestion_runs(job_id, started_at DESC);

-- Last known-good payload per feed, so a failed upstream serves real (dated)
-- data instead of nothing. Survives restarts, which the in-process TTL cache
-- does not — a cold start after a container restart was the one case where a
-- transient upstream failure left a panel with no data at all.
CREATE TABLE IF NOT EXISTS last_good (
    key          TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    saved_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Index membership (NIFTY 50, Bank Nifty, sector indices …), ingested from the
-- official NSE constituent CSVs. Previously these lists were literals in
-- services/nifty50.py, which drifted the moment NSE rejigged an index — the
-- hardcoded Bank Nifty was already missing UNIONBANK and YESBANK.
-- `industry` is NSE's own sector label for the stock, from the same CSV.
CREATE TABLE IF NOT EXISTS index_members (
    index_key   TEXT NOT NULL,
    index_name  TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    industry    TEXT,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (index_key, symbol)
);
CREATE INDEX IF NOT EXISTS idx_index_members_symbol ON index_members(symbol);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    component TEXT,
    message TEXT,
    severity TEXT CHECK(severity IN ('DEBUG', 'INFO', 'WARNING', 'ERROR')) DEFAULT 'INFO',
    metadata_json TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- ============================================
-- Indexes for Performance
-- ============================================

-- Symbol master lookups
CREATE INDEX IF NOT EXISTS idx_symbol_master_industry ON symbol_master(industry);
CREATE INDEX IF NOT EXISTS idx_symbol_master_cap_segment ON symbol_master(cap_segment);
CREATE INDEX IF NOT EXISTS idx_symbol_master_mcap_rank ON symbol_master(mcap_rank);
CREATE INDEX IF NOT EXISTS idx_symbol_master_sector ON symbol_master(sector);

-- Price queries
CREATE INDEX IF NOT EXISTS idx_prices_daily_date ON prices_daily(date);
CREATE INDEX IF NOT EXISTS idx_prices_daily_symbol ON prices_daily(symbol);
-- Composite covering the "latest row per symbol" access pattern (universe
-- endpoint, per-symbol history lookups) — the two single-column indexes
-- above don't help SQLite pick the last date per symbol without a scan.
CREATE INDEX IF NOT EXISTS idx_prices_daily_symbol_date ON prices_daily(symbol, date DESC);

-- Shareholding queries
CREATE INDEX IF NOT EXISTS idx_shareholding_quarter ON shareholding(quarter);
CREATE INDEX IF NOT EXISTS idx_shareholding_symbol ON shareholding(symbol);

-- Cache cleanup
CREATE INDEX IF NOT EXISTS idx_agent_cache_expires ON agent_cache(expires_at);
CREATE INDEX IF NOT EXISTS idx_search_cache_expires ON search_cache(expires_at);

-- Audit log queries
CREATE INDEX IF NOT EXISTS idx_audit_log_type ON audit_log(event_type);
CREATE INDEX IF NOT EXISTS idx_audit_log_created ON audit_log(created_at);

-- ============================================
-- User Data: Alerts + Watchlists
-- ============================================
-- These three were created inline by the API handlers (_ensure_alerts /
-- _ensure_watchlists in api/server.py), so a fresh database only grew them
-- once someone hit the matching route. They belong here with the rest of the
-- schema; init_database() re-runs this file on every start and every statement
-- is IF NOT EXISTS, so this is a no-op on a database that already has them.

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    type TEXT NOT NULL,
    condition TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS watchlists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    created TEXT NOT NULL DEFAULT (datetime('now'))
);

-- The ON DELETE CASCADE only fires on a connection that has
-- PRAGMA foreign_keys=ON; api/server.py's watchlists_delete sets it per-call.
CREATE TABLE IF NOT EXISTS watchlist_items (
    list_id INTEGER NOT NULL REFERENCES watchlists(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    added TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (list_id, symbol)
);

-- ============================================
-- Triggers for Auto-update
-- ============================================

-- Update updated_at on symbol_master changes
CREATE TRIGGER IF NOT EXISTS trigger_symbol_master_updated
AFTER UPDATE ON symbol_master
BEGIN
    UPDATE symbol_master SET updated_at = datetime('now') WHERE symbol = NEW.symbol;
END;

-- Update computed_metrics updated_at
CREATE TRIGGER IF NOT EXISTS trigger_computed_metrics_updated
AFTER UPDATE ON computed_metrics
BEGIN
    UPDATE computed_metrics SET updated_at = datetime('now') WHERE symbol = NEW.symbol;
END;

-- ============================================
-- Seed Data (Optional - for testing)
-- ============================================

-- Example indices (will be populated by ETL)
-- INSERT INTO symbol_master ...