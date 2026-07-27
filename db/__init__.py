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


def dict_fetchone(cursor) -> dict | None:
    """Fetch one row as dictionary."""
    row = cursor.fetchone()
    return dict(row) if row else None


def dict_fetchall(cursor) -> list[dict]:
    """Fetch all rows as list of dictionaries."""
    rows = cursor.fetchall()
    return [dict(row) for row in rows]


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