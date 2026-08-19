"""Shared pytest configuration.

Most of the suite is hermetic — it builds its own in-memory schema or asserts on
pure functions. A handful of tests deliberately assert against the REAL contents
of db/artha.db (that index membership resolves, that a screen grounds on actual
constituents), because that is the bug class they were written to catch. Those
cannot pass on a fresh checkout or in CI, where the database is gitignored and
empty.

Rather than drop them from CI with a brittle --ignore list that silently rots,
they carry @pytest.mark.needs_data and skip themselves when the database has no
symbols. Locally, where the DB is populated, they run exactly as before.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


def _has_symbol_data() -> bool:
    try:
        from db import get_connection
        with get_connection() as conn:
            return conn.execute("SELECT 1 FROM symbol_master LIMIT 1").fetchone() is not None
    except Exception:
        # No file, no schema, no table — all mean the same thing here.
        return False


def pytest_configure(config):
    config.addinivalue_line("markers", "needs_data: requires a populated db/artha.db")


def pytest_collection_modifyitems(config, items):
    if _has_symbol_data():
        return
    skip = pytest.mark.skip(reason="needs a populated db/artha.db (run scripts/ingest_all.py)")
    for item in items:
        if "needs_data" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _reset_auth_rate_limit():
    """api.server's login/register rate limiter is a module-level dict keyed
    by client IP — every test using Starlette's TestClient shares one fixed
    IP ("testclient"), so hits accumulate across unrelated tests in the same
    session and a later test starts pre-throttled. Real deployments don't hit
    this: it's an artefact of every test sharing one process and one fake IP."""
    try:
        from api.server import _AUTH_ATTEMPTS
        _AUTH_ATTEMPTS.clear()
    except Exception:
        pass
    yield
