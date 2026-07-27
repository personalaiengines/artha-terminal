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
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
import json
import logging
from datetime import datetime
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
    from ingestion.price_etl import PriceETL
    return PriceETL().run()


def _run_fundamentals_etl():
    from ingestion.fundamentals_etl import FundamentalsETL
    return FundamentalsETL().run()


def _run_compute_metrics():
    from ingestion.compute_metrics import MetricsCalculator
    return MetricsCalculator().run()


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
    {"id": "fundamentals_etl", "name": "Fundamentals ETL",
     "trigger": CronTrigger(hour=21, minute=30, day_of_week="wed", timezone="Asia/Kolkata"),
     "fn": _run_fundamentals_etl},
    {"id": "compute_metrics", "name": "Compute Metrics ETL",
     "trigger": CronTrigger(hour=22, minute=0, timezone="Asia/Kolkata"),
     "fn": _run_compute_metrics},
    {"id": "cache_cleanup", "name": "Cache Cleanup",
     "trigger": CronTrigger(hour=3, minute=0, timezone="Asia/Kolkata"),
     "fn": _run_cache_cleanup},
    {"id": "fno_game_plan", "name": "F&O Game Plan + TradingView draw",
     "trigger": CronTrigger(hour=8, minute=45, day_of_week="mon-fri", timezone="Asia/Kolkata"),
     "fn": _run_fno_game_plan},
]


def _tracked(job_id: str, fn):
    """Run fn(), recording start/finish/status/stats in ingestion_runs so the
    status API has something to report regardless of how the job was
    triggered (cron, manual docker exec, /api/ingestion/run)."""
    run_id = None
    try:
        with get_connection() as conn:
            cur = conn.execute(
                "INSERT INTO ingestion_runs (job_id, started_at, status) VALUES (?, ?, 'running')",
                (job_id, datetime.now().isoformat()),
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
                    (datetime.now().isoformat(), json.dumps(result, default=str)[:4000], run_id),
                )
                conn.commit()
        return result
    except Exception as e:
        if run_id is not None:
            with get_connection() as conn:
                conn.execute(
                    "UPDATE ingestion_runs SET finished_at=?, status='error', error=? WHERE id=?",
                    (datetime.now().isoformat(), str(e)[:2000], run_id),
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
                "last_run": None if not row else {
                    "started_at": row["started_at"],
                    "finished_at": row["finished_at"],
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

    _scheduler = schedule_ingestion_jobs()
    _scheduler.start()
    logger.info("Ingestion scheduler started")

    return _scheduler


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
