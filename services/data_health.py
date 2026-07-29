"""
ARTHA Terminal - Data health / liveness

Every screen in this app serves whatever the DB last managed to fetch. That is
the right behaviour — a stale real number beats a blank or a fabricated one —
but only if the user is told which numbers are stale. This module answers
"what is not live right now, since when, and what is being served instead".

One check per upstream the UI actually depends on. Each returns an issue dict
or None:

    {"source", "severity" ("warn"|"error"), "title", "detail",
     "last_good" (iso|None), "fix"}

Nothing here fetches — it reads what ingestion already recorded, so the checks
are cheap enough to poll.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from db import get_connection

IST = timezone(timedelta(hours=5, minutes=30))

# NSE reviews index composition roughly twice a year, but the ETL runs weekly —
# a fortnight without a successful pull means the feed, not the calendar.
INDEX_MEMBERS_MAX_AGE_DAYS = 14

# Share of the symbol universe allowed to miss the latest session before this
# counts as a feed problem.
#
# A full trading day of monitoring showed "50 of 5005 symbols have no candle"
# in 272 of 272 samples — never once clearing. Those 50 are delisted, suspended
# or untraded names that will never get another candle, so the card sat amber
# all day while every feed was in fact healthy. An alert that is always on is
# an alert nobody reads. Real outages take out far more than 1% at once.
PRICE_STALE_SHARE = 0.05


def _age_days(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        ts = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - ts).total_seconds() / 86400


def _check_index_members() -> dict | None:
    """Index/sector membership — powers the movers slices and breadth."""
    from services.constituents import last_updated

    ts = last_updated()
    if ts is None:
        return {
            "source": "index_members",
            "severity": "error",
            "title": "Index & sector membership unavailable",
            "detail": ("The NSE constituent lists have never been ingested, so the "
                       "per-index and per-sector movers slices are empty. No "
                       "hardcoded fallback exists by design."),
            "last_good": None,
            "fix": "Run the 'Index Membership' job from Settings, or wait for the weekly schedule.",
        }
    age = _age_days(ts)
    if age is not None and age > INDEX_MEMBERS_MAX_AGE_DAYS:
        return {
            "source": "index_members",
            "severity": "warn",
            "title": "Index & sector membership is not live",
            "detail": (f"Last successful pull from NSE was {age:.0f} days ago. Serving that "
                       f"membership. If an index has been rejigged since, its slice will "
                       f"under- or over-report."),
            "last_good": ts,
            "fix": "Re-run the 'Index Membership' job from Settings once NSE is reachable.",
        }
    return None


def _check_prices() -> dict | None:
    """prices_daily vs the latest trading session we know of."""
    from ingestion.quotes import latest_trading_date

    try:
        target = latest_trading_date()
    except Exception:
        target = None
    if not target:
        return None

    with get_connection() as conn:
        row = conn.execute("SELECT MAX(date) AS d, COUNT(DISTINCT symbol) AS n "
                           "FROM prices_daily").fetchone()
        behind = conn.execute(
            "SELECT COUNT(*) AS n FROM (SELECT symbol, MAX(date) d FROM prices_daily "
            "GROUP BY symbol) WHERE d < ?", (target,)).fetchone()["n"]

    if not row or not row["d"]:
        return {
            "source": "prices",
            "severity": "error",
            "title": "No price data",
            "detail": "prices_daily is empty — every price on screen would be blank.",
            "last_good": None,
            "fix": "Run the 'Price Data ETL' job from Settings.",
        }
    total = row["n"] or 0
    if behind and total and behind / total > PRICE_STALE_SHARE:
        return {
            "source": "prices",
            "severity": "warn",
            "title": "Some prices are not live",
            "detail": (f"{behind} of {total} symbols ({behind / total:.0%}) have no candle "
                       f"for {target}; their last known close is being shown instead."),
            "last_good": row["d"],
            "fix": "Runs automatically every 3 min during market hours; "
                   "'Live Quotes' in Settings forces it now.",
        }
    return None


def _check_upstox() -> dict | None:
    """The PORTFOLIO token (config.upstox.access_token).

    Deliberately separate from the market-data token below: they are two
    different credentials and only one of them is usually expired. Reporting
    "Upstox is down" off this one alone would claim index ticks were dark while
    the market-data feed was in fact streaming fine.
    """
    from services.upstox_auth import check_access_token, token_saved_at

    try:
        st = check_access_token()
    except Exception as e:
        return {"source": "upstox_portfolio", "severity": "warn",
                "title": "Upstox status unavailable", "detail": str(e),
                "last_good": None, "fix": "Check the API container logs."}
    if st.get("status") == "ok":
        return None
    return {
        "source": "upstox_portfolio",
        "severity": "error",
        "title": "Portfolio data is not live",
        "detail": ("The Upstox portfolio token has expired, so holdings, P&L and "
                   "the portfolio curve are showing the last values fetched while "
                   "it was valid. Market data is unaffected."),
        "last_good": token_saved_at(),
        "fix": "Re-authorize from the banner or Settings — tokens expire daily (~03:30 IST).",
    }


def _check_market_feed() -> dict | None:
    """The market-data token + tick stream — what makes index levels move live."""
    from config import config

    if not config.upstox.analytics_token:
        return {
            "source": "upstox_feed",
            "severity": "error",
            "title": "Live market feed is not connected",
            "detail": ("No Upstox market-data token, so index levels come from the "
                       "~15-min-delayed Yahoo feed and do not tick during the session."),
            "last_good": None,
            "fix": "Set UPSTOX_ANALYTICS_TOKEN (or re-authorize) and restart the API.",
        }

    from services.upstox_stream import get_stream_manager
    st = get_stream_manager().status()
    if not st["started"] or st["connected"]:
        # Not started = this process doesn't run the stream (tests, scripts).
        return None
    return {
        "source": "upstox_feed",
        "severity": "warn",
        "title": "Live index ticks are not streaming",
        "detail": ("The Upstox market-data socket is disconnected and retrying. "
                   "Index levels are still refreshed by the 20s REST poll, so they "
                   "are current but not tick-by-tick."),
        "last_good": None,
        "fix": "Reconnects automatically with backoff; re-authorize if it persists.",
    }


def _check_stale_feeds() -> list[dict]:
    """Feeds currently answering from services/last_good.py rather than live.

    A panel showing dated data carries its own "Out of date" chip, but that is
    only seen by whoever happens to be on that page. The same fact belongs on
    the Alerts page, where the user goes to ask "what is wrong right now".
    """
    labels = {"pulse": "Market breadth & sector rotation"}
    out = []
    with get_connection() as conn:
        try:
            rows = conn.execute("SELECT key, saved_at FROM last_good").fetchall()
        except Exception:
            return []

    for r in rows:
        # Only a feed whose *current* served value is the fallback matters, and
        # that is exactly the one whose last good save has aged past its cache
        # window without being refreshed.
        age_h = (_age_days(r["saved_at"]) or 0) * 24
        if age_h < 1:
            continue
        out.append({
            "source": f"feed:{r['key']}",
            "severity": "warn",
            "title": f"{labels.get(r['key'], r['key'])} is out of date",
            "detail": (f"The upstream has not answered successfully for {age_h:.0f}h. "
                       f"The last values confirmed good are still being shown, "
                       f"labelled as out of date on the page."),
            "last_good": r["saved_at"],
            "fix": "Recovers on its own once the upstream responds; no action needed.",
        })
    return out


def _check_ingestion_jobs() -> list[dict]:
    """Any ETL whose most recent run failed."""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT r.job_id, r.finished_at, r.started_at, r.status, r.error
              FROM ingestion_runs r
              JOIN (SELECT job_id, MAX(started_at) AS m FROM ingestion_runs GROUP BY job_id) l
                ON l.job_id = r.job_id AND l.m = r.started_at
             WHERE r.status = 'error'
        """).fetchall()

    out = []
    for r in rows:
        # A run killed by a container restart is marked 'error' by
        # scheduler._close_orphan_runs. That is a restart, not a broken feed —
        # reporting it as a data-health problem trains the user to ignore the
        # card. It re-runs on its normal schedule.
        if r["error"] and r["error"].startswith("Interrupted"):
            continue
        with get_connection() as conn:
            good = conn.execute(
                "SELECT MAX(finished_at) AS t FROM ingestion_runs "
                "WHERE job_id = ? AND status = 'success'", (r["job_id"],)).fetchone()
        out.append({
            "source": f"etl:{r['job_id']}",
            "severity": "warn",
            "title": f"{r['job_id']} last run failed",
            "detail": (r["error"] or "No error recorded.")[:300] +
                      " — the previous successful result is still being served.",
            "last_good": good["t"] if good else None,
            "fix": "Re-run it from Settings; it also retries on its normal schedule.",
        })
    return out


def get_data_health() -> dict:
    """{"ok", "live", "issues": [...], "checked_ist"} — ok is the call itself."""
    issues: list[dict] = []
    for check in (_check_index_members, _check_prices, _check_upstox, _check_market_feed):
        try:
            issue = check()
        except Exception as e:
            issue = {"source": check.__name__, "severity": "warn",
                     "title": "Health check failed", "detail": str(e),
                     "last_good": None, "fix": "Check the API container logs."}
        if issue:
            issues.append(issue)
    for extra in (_check_stale_feeds, _check_ingestion_jobs):
        try:
            issues.extend(extra())
        except Exception:
            pass

    # Errors first — the UI shows the worst one in the global banner.
    issues.sort(key=lambda i: 0 if i["severity"] == "error" else 1)
    return {
        "ok": True,
        "live": not issues,
        "issues": issues,
        "checked_ist": datetime.now(IST).isoformat(),
    }


__all__ = ["get_data_health"]
