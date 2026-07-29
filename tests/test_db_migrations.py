"""
ARTHA Terminal - agent_cache/search_cache CHECK-constraint migration test

SQLite can't ALTER a CHECK constraint in place, so db/__init__.py's
_add_check_value() rebuilds the table (rename/recreate/copy/drop) instead.
This verifies: pre-migration the new values are rejected, existing rows
survive the rebuild, and post-migration the new values are accepted.
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from db import _apply_migrations

_OLD_AGENT_CACHE = """
CREATE TABLE agent_cache (
    key TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    analysis_type TEXT CHECK(analysis_type IN
        ('deep_dive', 'swot', 'verdict', 'sector_outlook', 'red_flags')) NOT NULL,
    content_json TEXT NOT NULL,
    model_used TEXT,
    tokens_used INTEGER,
    cache_at TEXT NOT NULL,
    ttl_hours INTEGER DEFAULT 6,
    expires_at TEXT NOT NULL,
    prompt_hash TEXT,
    tool_calls JSON,
    created_at TEXT DEFAULT (datetime('now'))
)
"""

_OLD_SEARCH_CACHE = """
CREATE TABLE search_cache (
    key TEXT PRIMARY KEY,
    query TEXT NOT NULL,
    sector TEXT,
    symbol TEXT,
    results_json TEXT NOT NULL,
    source TEXT CHECK(source IN ('serpapi', 'searxng', 'jina')) NOT NULL,
    cache_at TEXT NOT NULL,
    ttl_hours INTEGER NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
)
"""


def _old_schema_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(_OLD_AGENT_CACHE)
    conn.execute(_OLD_SEARCH_CACHE)
    conn.execute(
        "INSERT INTO agent_cache (key, symbol, analysis_type, content_json, cache_at, expires_at) "
        "VALUES ('old1','RELIANCE','deep_dive','{}','2026-01-01','2026-01-01')"
    )
    conn.commit()
    return conn


def test_new_check_values_rejected_before_migration():
    conn = _old_schema_conn()
    try:
        conn.execute(
            "INSERT INTO agent_cache (key, symbol, analysis_type, content_json, cache_at, expires_at) "
            "VALUES ('mn1','_MARKET','market_news','{}','2026-01-01','2026-01-01')"
        )
        assert False, "should have raised IntegrityError before migration"
    except sqlite3.IntegrityError:
        pass
    conn.close()


def test_migration_preserves_existing_rows_and_accepts_new_values():
    conn = _old_schema_conn()
    _apply_migrations(conn)
    conn.commit()

    row = conn.execute("SELECT symbol, analysis_type FROM agent_cache WHERE key='old1'").fetchone()
    assert row == ("RELIANCE", "deep_dive")

    conn.execute(
        "INSERT INTO agent_cache (key, symbol, analysis_type, content_json, cache_at, expires_at) "
        "VALUES ('mn1','_MARKET','market_news','{}','2026-01-01','2026-01-01')"
    )
    conn.execute(
        "INSERT INTO search_cache (key, query, results_json, source, cache_at, ttl_hours, expires_at) "
        "VALUES ('fh1','q','[]','finnhub','2026-01-01',6,'2026-01-01')"
    )
    conn.commit()
    conn.close()


def test_migration_is_idempotent():
    conn = _old_schema_conn()
    _apply_migrations(conn)
    _apply_migrations(conn)  # second run must be a no-op, not an error
    conn.commit()
    row = conn.execute("SELECT symbol FROM agent_cache WHERE key='old1'").fetchone()
    assert row == ("RELIANCE",)
    conn.close()
