"""
ARTHA Terminal - Database Module
SQLite initialization and connection management.
"""

import sqlite3
from pathlib import Path
from contextlib import contextmanager
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import config


def init_database(db_path: Path = None) -> Path:
    """
    Initialize SQLite database with WAL mode.

    Args:
        db_path: Path to database file (uses config default if None)

    Returns:
        Path to created database file
    """
    if db_path is None:
        db_path = config.db_path

    # Ensure directory exists
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Read and execute schema
    schema_path = Path(__file__).parent / "schema.sql"

    with sqlite3.connect(str(db_path)) as conn:
        # Enable WAL mode
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=10000")

        # Read and execute schema
        if schema_path.exists():
            schema = schema_path.read_text(encoding="utf-8")
            conn.executescript(schema)
            conn.commit()
            print(f"[OK] Database initialized: {db_path}")
        else:
            print(f"[WARN] Schema file not found: {schema_path}")

        _apply_migrations(conn)
        conn.commit()

    return db_path


def _apply_migrations(conn: sqlite3.Connection) -> None:
    """
    Bring an existing database up to the current schema.

    `CREATE TABLE IF NOT EXISTS` is a no-op on databases that already exist, so
    columns added to schema.sql after a database was created must be applied
    here too. Each step is idempotent.
    """
    # prices_daily.updated_at: PriceETL's UPDATE branch writes this column. Without
    # it every update of an existing candle raises "no such column: updated_at",
    # which the ETL swallows — silently making price ingestion append-only.
    cols = {row[1] for row in conn.execute("PRAGMA table_info(prices_daily)")}
    if cols and "updated_at" not in cols:
        # SQLite rejects a non-constant DEFAULT in ALTER TABLE ADD COLUMN, so the
        # column is added bare; the ETL sets it explicitly on write.
        conn.execute("ALTER TABLE prices_daily ADD COLUMN updated_at TEXT")
        print("[OK] Migration: added prices_daily.updated_at")

    # fii_dii_flows: daily institutional net-flow readings, accumulated for trend.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS fii_dii_flows (
            date TEXT PRIMARY KEY,
            fii_net REAL, dii_net REAL,
            fii_buy REAL, fii_sell REAL,
            dii_buy REAL, dii_sell REAL,
            created_at TEXT DEFAULT (datetime('now'))
        )
        """
    )

    # fno_pnl_daily: one row per trading day of F&O P&L. Upstox's positions API
    # is intraday-only — it forgets yesterday — so a tracker across sessions has
    # to keep its own record. Written on every positions read; the last write of
    # a day is that day's close.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS fno_pnl_daily (
            date TEXT PRIMARY KEY,
            realized REAL NOT NULL DEFAULT 0,
            unrealized REAL NOT NULL DEFAULT 0,
            net REAL NOT NULL DEFAULT 0,
            open_count INTEGER NOT NULL DEFAULT 0,
            closed_count INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        )
        """
    )

    # fno_pnl_daily.source: 'live' (read off the broker's position book, carries
    # unrealised too) or 'trades' (reconstructed from trade history, booked-only).
    # The backfill must never overwrite a live row with a booked-only one.
    cols = {row[1] for row in conn.execute("PRAGMA table_info(fno_pnl_daily)")}
    if cols and "source" not in cols:
        conn.execute("ALTER TABLE fno_pnl_daily ADD COLUMN source TEXT DEFAULT 'live'")
        print("[OK] Migration: added fno_pnl_daily.source")

    # fno_pnl_contract_daily: the same day, broken down by contract. Keeps the
    # tracker's filters (index, CE/PE, winners/losers) meaningful across the
    # whole window instead of only for whatever the broker still has open now.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS fno_pnl_contract_daily (
            date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            realized REAL NOT NULL DEFAULT 0,
            unrealized REAL NOT NULL DEFAULT 0,
            net REAL NOT NULL DEFAULT 0,
            qty INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (date, symbol)
        )
        """
    )

    # SQLite can't ALTER a CHECK constraint in place — rebuild the table (the
    # standard SQLite recipe: rename, recreate, copy, drop) only if the new
    # value isn't already accepted, so this is a no-op on every later startup.
    _add_check_value(conn, "agent_cache", "market_news",
        """CREATE TABLE agent_cache (
            key TEXT PRIMARY KEY,
            symbol TEXT NOT NULL REFERENCES symbol_master(symbol),
            analysis_type TEXT CHECK(analysis_type IN
                ('deep_dive', 'swot', 'verdict', 'sector_outlook', 'red_flags', 'market_news')) NOT NULL,
            content_json TEXT NOT NULL,
            model_used TEXT,
            tokens_used INTEGER,
            cache_at TEXT NOT NULL,
            ttl_hours INTEGER DEFAULT 6,
            expires_at TEXT NOT NULL,
            prompt_hash TEXT,
            tool_calls JSON,
            created_at TEXT DEFAULT (datetime('now'))
        )""",
        ["CREATE INDEX IF NOT EXISTS idx_agent_cache_expires ON agent_cache(expires_at)"])

    _add_check_value(conn, "search_cache", "finnhub",
        """CREATE TABLE search_cache (
            key TEXT PRIMARY KEY,
            query TEXT NOT NULL,
            sector TEXT,
            symbol TEXT,
            results_json TEXT NOT NULL,
            source TEXT CHECK(source IN ('serpapi', 'searxng', 'jina', 'finnhub')) NOT NULL,
            cache_at TEXT NOT NULL,
            ttl_hours INTEGER NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )""",
        ["CREATE INDEX IF NOT EXISTS idx_search_cache_expires ON search_cache(expires_at)"])


def _add_check_value(conn: sqlite3.Connection, table: str, value: str,
                      create_sql: str, index_sql: list[str]) -> None:
    """Rebuild `table` with a CHECK constraint that additionally allows
    `value`, unless it already does. `create_sql` is the full new CREATE
    TABLE statement (with the widened CHECK already baked in)."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    if not row or not row[0] or value in row[0]:
        return  # table missing (fresh schema.sql already has it) or already migrated
    conn.execute(f"ALTER TABLE {table} RENAME TO {table}_old")
    conn.execute(create_sql)
    conn.execute(f"INSERT INTO {table} SELECT * FROM {table}_old")
    conn.execute(f"DROP TABLE {table}_old")
    for stmt in index_sql:
        conn.execute(stmt)
    print(f"[OK] Migration: {table} CHECK constraint now allows '{value}'")


@contextmanager
def get_connection(db_path: Path = None):
    """
    Context manager for database connections.

    Usage:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM ...")
    """
    if db_path is None:
        db_path = config.db_path

    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.row_factory = sqlite3.Row  # Enable dict-like access
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


# Initialize database on import
if __name__ == "__main__":
    import os
    from pathlib import Path

    # Check for Docker-style env var path first
    env_path = os.getenv("ARTHA_DB_PATH")
    if env_path:
        db_path = init_database(Path(env_path))
    else:
        db_path = init_database()

    print(f"✅ Database ready at: {db_path}")
    print(f"   Tables: ", end="")
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [t[0] for t in cursor.fetchall()]
    print(tables)
    conn.close()