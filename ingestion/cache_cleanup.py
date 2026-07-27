"""
ARTHA Terminal - Cache Cleanup
Periodic cleanup of expired cache entries.
"""

import sqlite3
from datetime import datetime
from typing import Dict
import logging

from db import get_connection

logger = logging.getLogger("ingestion.cache_cleanup")


class CacheCleanup:
    """Cleanup expired cache entries from agent_cache and search_cache."""

    def run(self) -> Dict[str, int]:
        """
        Run cache cleanup.

        Returns:
            Statistics about cleanup
        """
        logger.info("Starting cache cleanup...")

        stats = {
            "agent_cache_removed": 0,
            "search_cache_removed": 0,
            "errors": 0,
        }

        try:
            with get_connection() as conn:
                cursor = conn.cursor()

                # Clean expired agent cache entries
                cursor.execute(
                    """
                    DELETE FROM agent_cache
                    WHERE datetime(expires_at) < datetime('now')
                    """,
                )
                stats["agent_cache_removed"] = cursor.rowcount

                # Clean expired search cache entries
                cursor.execute(
                    """
                    DELETE FROM search_cache
                    WHERE datetime(expires_at) < datetime('now')
                    """,
                )
                stats["search_cache_removed"] = cursor.rowcount

                conn.commit()

            logger.info(
                f"Cache cleanup completed: "
                f"removed {stats['agent_cache_removed']} agent entries, "
                f"{stats['search_cache_removed']} search entries"
            )

            return {"status": "success", **stats}

        except Exception as e:
            logger.error(f"Cache cleanup failed: {e}")
            stats["errors"] += 1
            return {"status": "error", "error": str(e), **stats}