"""
ARTHA Terminal - Ingestion Scheduler
APScheduler for nightly ETL jobs (post market close ~20:30 IST).

Every job run is recorded in the ingestion_runs table (start/finish/status/
stats), so get_ingestion_status() can report last-run/next-run/success without
needing the live scheduler process to answer — that's what the Alerts-page
ingestion monitor reads.
"""

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import config
from db import get_connection

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if config.app.debug else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("ingestion.scheduler")


def on_job_event(event):
    """Log job events."""
    if event.exception:
        logger.error(f"Job {event.job_id} failed: {event.exception}")
    else:
        logger.info(f"Job {event.job_id} completed successfully")


# ============================================
# Job bodies
# ============================================

def _run_symbol_etl():
    from ingestion.symbol_etl import SymbolETL
    return SymbolETL().run()


def _run_price_etl():
    """Nightly close refresh, batched.

    Was PriceETL().run() — one HTTP request per symbol over ~3100 symbols. It
    ran 30-50 minutes and drew a rate limit partway through: the last real run
    reached 1443 of 3117 symbols, so 1704 symbols kept serving a days-old close
    everywhere in the app. ingestion.quotes does the same job in ~33 batched
    requests and about two minutes.

    PriceETL is still the tool for deep history (years of candles for a new
    symbol); this job only keeps the recent tail current.
    """
    from ingestion import quotes
    return quotes.refresh_best()


def _run_live_quotes():
    """Keep prices current during the session (Upstox, ~4.4s for the universe).

    The app previously showed the previous session's close all day, because the
    only price source was a nightly Yahoo crawl. Upstox is authenticated and
    unmetered, so refreshing every few minutes costs 11 requests and is what
    makes the screener and portfolio read live instead of yesterday.
    """
    from services import live_quotes
    if not live_quotes.available():
        return {"status": "skipped", "reason": "no upstox analytics token"}
    return live_quotes.refresh()


# NOTE: the bulk fundamentals crawl is deliberately NOT scheduled.
# Fundamentals are now ingested on demand (services/freshness.py): a page view
# refreshes the symbols on screen and writes them through to the DB, so data
# follows real usage instead of a cron grinding thousands of symbols nobody
# opens. FundamentalsETL still exists for a manual one-off seed.


def _run_compute_metrics():
    from ingestion.compute_metrics import MetricsCalculator
    return MetricsCalculator().run()


def _run_index_history():
    from ingestion import index_history
    return index_history.run()


def _run_index_members():
    from ingestion.index_members import run
    return run()


def _run_compute_scores():
    from ingestion.compute_scores import ScoreETL
    return ScoreETL().run()


def _run_cache_cleanup():
    from ingestion.cache_cleanup import CacheCleanup
    return CacheCleanup().run()


def _run_fno_game_plan():
    """
    Daily F&O game plan for NIFTY / BANK NIFTY / SENSEX: compute levels, snapshot
    each plan to JSON (history/audit), then draw the levels on TradingView.

    The draw dry-runs safely if the tradingview-mcp CLI / TV Desktop isn't set up,
    so this job never fails on a missing bridge.
    """
    import json as _json
    from datetime import datetime as _datetime
    from zoneinfo import ZoneInfo
    from services.fno_service import build_game_plan, INDEXES
    from services.tradingview_bridge import draw_levels

    out_dir = config.db_path.parent / "fno_plans"
    out_dir.mkdir(parents=True, exist_ok=True)
    date = _datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()

    results = {}
    for index in INDEXES:
        try:
            plan = build_game_plan(index)
            if not plan.get("ok"):
                logger.warning(f"F&O {index}: {plan.get('error')}")
                results[index] = {"ok": False, "error": plan.get("error")}
                continue
            snap = {k: v for k, v in plan.items() if k != "strikes"}
            (out_dir / f"{index}_{date}.json").write_text(
                _json.dumps(snap, indent=2, default=str), encoding="utf-8")

            draw = draw_levels(index, plan.get("levels", []))
            logger.info(
                f"F&O {index}: bias {plan['bias']['label']} ({plan['bias']['score']}), "
                f"{len(plan['levels'])} levels, draw mode={draw.get('mode')}"
            )
            results[index] = {"ok": True, "bias": plan["bias"]["label"],
                              "levels": len(plan["levels"]), "draw": draw.get("mode")}
        except Exception as e:
            logger.error(f"F&O {index} failed: {e}")
            results[index] = {"ok": False, "error": str(e)}

    logger.info(f"F&O game-plan job complete: {results}")
    return results


def _run_market_news_curation():
    """HSTR-lite: pre-compute curated market news into agent_cache on a fixed
    cadence instead of at request time. This is the concrete "structure it
    before query time" change — the curation logic itself
    (services.market_news.get_live_market_news) is unchanged, only when it
    runs moves from request-triggered to scheduler-triggered."""
    import json as _json
    from datetime import datetime as _datetime, timedelta as _timedelta
    from services.market_news import get_live_market_news

    result = get_live_market_news()
    now = _datetime.now()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO agent_cache (key, symbol, analysis_type, content_json, cache_at, ttl_hours, expires_at)
               VALUES ('market_news', '_MARKET', 'market_news', ?, ?, 1, ?)
               ON CONFLICT(key) DO UPDATE SET
                   content_json=excluded.content_json, cache_at=excluded.cache_at, expires_at=excluded.expires_at""",
            (_json.dumps(result, default=str), now.isoformat(), (now + _timedelta(hours=1)).isoformat()),
        )
        conn.commit()
    return {"items": len(result.get("items", [])), "ok": result.get("ok")}


# Single source of truth for id/name/schedule/fn — used to register the
# APScheduler jobs AND to compute "next run" for the status API, so the two
# can never drift apart. All times are IST (this is an Indian-markets app).
JOBS = [
    {"id": "symbol_etl", "name": "Symbol Master ETL",
     "trigger": CronTrigger(hour=21, minute=0, day_of_week="mon", timezone="Asia/Kolkata"),
     "fn": _run_symbol_etl},
    {"id": "price_etl", "name": "Price Data ETL",
     "trigger": CronTrigger(hour=20, minute=30, timezone="Asia/Kolkata"),
     "fn": _run_price_etl},
    {"id": "live_quotes", "name": "Live Quotes (intraday)",
     # Every 3 min through the NSE session (09:15-15:30 IST). The 9 and 15
     # hours include a few minutes either side of the bell; a refresh outside
     # the session just rewrites the same settled candle, which is harmless.
     "trigger": CronTrigger(day_of_week="mon-fri", hour="9-15", minute="*/3",
                            timezone="Asia/Kolkata"),
     "fn": _run_live_quotes},
    {"id": "index_history", "name": "Index OHLC History",
     # Three requests; runs with the nightly price ETL so the F&O chart has
     # real candles for NIFTY / BANKNIFTY / SENSEX.
     "trigger": CronTrigger(hour=20, minute=45, timezone="Asia/Kolkata"),
     "fn": _run_index_history},
    {"id": "index_members", "name": "Index Membership (NSE constituents)",
     # Weekly, just before the symbol master — index/sector membership feeds
     # the movers slices, breadth and sector peers. NSE rejigs composition
     # roughly twice a year, so weekly is ample; the point of scheduling it at
     # all is that nothing then rots silently the way a hardcoded list does.
     "trigger": CronTrigger(hour=20, minute=15, day_of_week="sun", timezone="Asia/Kolkata"),
     "fn": _run_index_members},
    {"id": "compute_metrics", "name": "Compute Metrics ETL",
     "trigger": CronTrigger(hour=22, minute=0, timezone="Asia/Kolkata"),
     "fn": _run_compute_metrics},
    {"id": "compute_scores", "name": "Analysis Score ETL",
     # After compute_metrics (22:00) — it reads the metrics it writes.
     "trigger": CronTrigger(hour=22, minute=30, timezone="Asia/Kolkata"),
     "fn": _run_compute_scores},
    {"id": "cache_cleanup", "name": "Cache Cleanup",
     "trigger": CronTrigger(hour=3, minute=0, timezone="Asia/Kolkata"),
     "fn": _run_cache_cleanup},
    {"id": "fno_game_plan", "name": "F&O Game Plan + TradingView draw",
     "trigger": CronTrigger(hour=8, minute=45, day_of_week="mon-fri", timezone="Asia/Kolkata"),
     "fn": _run_fno_game_plan},
    {"id": "market_news_curation", "name": "Market News Curation (HSTR-lite)",
     "trigger": IntervalTrigger(minutes=10, timezone="Asia/Kolkata"),
     "fn": _run_market_news_curation},
]


IST = timezone(timedelta(hours=5, minutes=30))


def _stamp() -> str:
    """Timezone-aware IST timestamp for ingestion_runs.

    These used to be written as bare `datetime.now().isoformat()`. In a UTC
    container that produced "2026-07-29T10:12:03" with no offset, and JS parses
    an offset-less ISO string as *local* time — so the Alerts and Settings
    panels rendered a job that had just finished as "7h ago", right next to a
    correctly-computed "Next: due now" (next_run carries +05:30 from the
    trigger). Same row, two time bases. Everything else the API emits
    (generated_ist, checked_ist, next_run) is IST-aware; match it.
    """
    return datetime.now(IST).isoformat()


def _as_ist(ts: str | None) -> str | None:
    """Attach an offset to legacy naive rows so old history renders correctly.

    Rows written before _stamp() existed are naive UTC (the container's clock).
    Reading them as IST would shift them 5.5h the other way, so label them UTC
    and let the client convert.
    """
    if not ts:
        return ts
    try:
        parsed = datetime.fromisoformat(ts)
    except ValueError:
        return ts
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.isoformat()


def _tracked(job_id: str, fn):
    """Run fn(), recording start/finish/status/stats in ingestion_runs so the
    status API has something to report regardless of how the job was
    triggered (cron, manual docker exec, /api/ingestion/run)."""
    run_id = None
    try:
        with get_connection() as conn:
            cur = conn.execute(
                "INSERT INTO ingestion_runs (job_id, started_at, status) VALUES (?, ?, 'running')",
                (job_id, _stamp()),
            )
            run_id = cur.lastrowid
            conn.commit()
    except Exception as e:
        logger.warning(f"Could not record run start for {job_id}: {e}")

    try:
        result = fn()
        if run_id is not None:
            with get_connection() as conn:
                conn.execute(
                    "UPDATE ingestion_runs SET finished_at=?, status='success', stats_json=? WHERE id=?",
                    (_stamp(), json.dumps(result, default=str)[:4000], run_id),
                )
                conn.commit()
        return result
    except Exception as e:
        if run_id is not None:
            with get_connection() as conn:
                conn.execute(
                    "UPDATE ingestion_runs SET finished_at=?, status='error', error=? WHERE id=?",
                    (_stamp(), str(e)[:2000], run_id),
                )
                conn.commit()
        raise


def schedule_ingestion_jobs():
    """Set up all ingestion jobs, each wrapped for run tracking."""
    scheduler = BackgroundScheduler(timezone="Asia/Kolkata")
    scheduler.add_listener(on_job_event, EVENT_JOB_ERROR | EVENT_JOB_EXECUTED)

    for job in JOBS:
        scheduler.add_job(
            func=lambda j=job: _tracked(j["id"], j["fn"]),
            trigger=job["trigger"],
            id=job["id"],
            name=job["name"],
            replace_existing=True,
        )

    return scheduler


def run_all_jobs():
    """Run all ETL jobs immediately (manual trigger / testing)."""
    logger.info("=== Running all ETL jobs manually ===")
    for job in JOBS:
        try:
            _tracked(job["id"], job["fn"])
        except Exception as e:
            logger.error(f"{job['id']} failed: {e}")
    logger.info("=== All ETL jobs completed ===")


# Ad-hoc runs launched from the Settings page. Kept out of the APScheduler
# thread pool so a manual run can never delay or displace a scheduled one.
_manual_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="manual-etl")
_running: set[str] = set()
_running_lock = threading.Lock()


def job_ids() -> list[str]:
    return [j["id"] for j in JOBS]


def is_running(job_id: str) -> bool:
    with _running_lock:
        return job_id in _running


def trigger_job(job_id: str) -> dict:
    """Run one ETL job now, in the background.

    Returns immediately rather than blocking the request: these jobs run from
    seconds (live quotes) to minutes (symbol master), well past any sane HTTP
    timeout. Progress is read back through get_ingestion_status(), which the
    Settings page polls — _tracked() already writes start/finish/stats/error
    into ingestion_runs for both scheduled and manual runs.
    """
    job = next((j for j in JOBS if j["id"] == job_id), None)
    if not job:
        return {"ok": False, "error": f"unknown job: {job_id}"}

    with _running_lock:
        if job_id in _running:
            return {"ok": False, "error": "already running", "job_id": job_id, "running": True}
        _running.add(job_id)

    def work():
        try:
            logger.info(f"manual trigger: {job['name']}")
            _tracked(job_id, job["fn"])
        except Exception as e:
            logger.error(f"manual {job_id} failed: {e}")
        finally:
            with _running_lock:
                _running.discard(job_id)

    _manual_pool.submit(work)
    return {"ok": True, "job_id": job_id, "name": job["name"], "started": True}


def get_ingestion_status() -> list[dict]:
    """Last run + next scheduled run for every ingestion job. Reads next-run
    straight off each CronTrigger, so this works even if the scheduler process
    isn't the one answering the request (e.g. computed from an API worker)."""
    now = datetime.now()
    out = []
    with get_connection() as conn:
        for job in JOBS:
            row = conn.execute(
                """SELECT started_at, finished_at, status, stats_json, error
                   FROM ingestion_runs WHERE job_id = ?
                   ORDER BY started_at DESC LIMIT 1""",
                (job["id"],),
            ).fetchone()
            next_fire = job["trigger"].get_next_fire_time(None, now.astimezone(job["trigger"].timezone))
            out.append({
                "id": job["id"],
                "name": job["name"],
                "running": is_running(job["id"]),
                "last_run": None if not row else {
                    "started_at": _as_ist(row["started_at"]),
                    "finished_at": _as_ist(row["finished_at"]),
                    "status": row["status"],
                    "stats": json.loads(row["stats_json"]) if row["stats_json"] else None,
                    "error": row["error"],
                },
                "next_run": next_fire.isoformat() if next_fire else None,
            })
    return out


# ============================================
# Start / stop
# ============================================

_scheduler = None


def start_scheduler():
    """Start the background scheduler."""
    global _scheduler

    if _scheduler is not None and _scheduler.running:
        logger.info("Scheduler already running")
        return _scheduler

    _close_orphan_runs()
    _scheduler = schedule_ingestion_jobs()
    _scheduler.start()
    logger.info("Ingestion scheduler started")

    return _scheduler


def _close_orphan_runs() -> None:
    """Mark runs left mid-flight by a restart as failed.

    A job killed with the process keeps status='running' forever, so the
    ingestion panel shows it as still working and its real failure never
    surfaces — which is precisely how a nightly price ETL could die every day
    unnoticed. Nothing can be running at startup, so any such row is an orphan.
    ('interrupted' isn't in the status CHECK constraint; 'error' with an
    explicit reason says the same thing without a migration.)
    """
    try:
        with get_connection() as conn:
            cur = conn.execute(
                "UPDATE ingestion_runs SET status='error', finished_at=?, "
                "error='Interrupted — the API process restarted before this run finished' "
                "WHERE status='running'", (_stamp(),))
            if cur.rowcount:
                logger.warning(f"closed {cur.rowcount} orphaned ingestion run(s) from a previous process")
            conn.commit()
    except Exception as e:
        logger.debug(f"orphan cleanup skipped: {e}")


def stop_scheduler():
    """Stop the scheduler."""
    global _scheduler

    if _scheduler:
        _scheduler.shutdown()
        _scheduler = None
        logger.info("Ingestion scheduler stopped")


# For direct execution
if __name__ == "__main__":
    import time

    print("Starting ARTHA Terminal Ingestion Scheduler...")
    print("Jobs will run at scheduled times (20:30 IST daily for prices)")
    print("Press Ctrl+C to stop\n")

    scheduler = start_scheduler()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop_scheduler()
        print("\nScheduler stopped.")
