"""
ARTHA Terminal - schema.sql completeness test

alerts / watchlists / watchlist_items used to be created inline by the API
handlers, so a fresh database only grew them once someone hit the matching
route. They now live in db/schema.sql; this fails if that DDL is ever dropped.
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from db import init_database


def test_schema_creates_alerts_and_watchlist_tables(tmp_path):
    db_path = init_database(tmp_path / "t.db")
    conn = sqlite3.connect(str(db_path))
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert {"alerts", "watchlists", "watchlist_items"} <= names
