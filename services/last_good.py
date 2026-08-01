"""
ARTHA Terminal - last known-good payloads

`_swr` in api/server.py already keeps serving a stale value when a background
refresh fails, but only for the life of the process and only once something
has been cached at all. The gaps it leaves:

  • cold start after a restart — nothing cached, so a failing upstream renders
    an empty panel
  • the upstream failing on the very first call of the process

Persisting each feed's last good payload closes both. The rule everywhere in
this app is the same: show real, dated data and say it is dated — never a
blank, never a differently-shaped substitute computed from another source.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from db import get_connection

logger = logging.getLogger("services.last_good")

IST = timezone(timedelta(hours=5, minutes=30))


def save(key: str, payload: dict) -> None:
    """Persist a good payload. Never raises — this is a side-channel."""
    try:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO last_good (key, payload_json, saved_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET "
                "payload_json = excluded.payload_json, saved_at = excluded.saved_at",
                (key, json.dumps(payload, default=str), datetime.now(IST).isoformat()),
            )
            conn.commit()
    except Exception as e:
        logger.warning(f"could not persist last-good {key}: {e}")


def load(key: str) -> tuple[dict | None, str | None]:
    """(payload, saved_at_iso) — (None, None) when nothing was ever stored."""
    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT payload_json, saved_at FROM last_good WHERE key = ?", (key,)
            ).fetchone()
        if row:
            return json.loads(row["payload_json"]), row["saved_at"]
    except Exception as e:
        logger.warning(f"could not read last-good {key}: {e}")
    return None, None


def serve(key: str, produce, is_good=lambda v: bool(v)) -> dict:
    """Run `produce()`; on success persist and return it, on failure fall back.

    The returned dict always carries `stale`, and when stale also `as_of` (when
    the data it is showing was actually good). Callers pass those through to the
    UI so a dated number is never read as a current one.
    """
    try:
        value = produce()
    except Exception as e:
        logger.warning(f"{key} failed, falling back to last known good: {e}")
        value = None

    if value is not None and is_good(value):
        save(key, value)
        return {**value, "stale": False, "as_of": None}

    cached, saved_at = load(key)
    if cached is None:
        # Nothing good has ever been fetched — say so rather than invent it.
        return {"ok": False, "stale": True, "as_of": None}
    logger.info(f"{key}: serving last known good from {saved_at}")
    return {**cached, "ok": True, "stale": True, "as_of": saved_at}


__all__ = ["save", "load", "serve"]
