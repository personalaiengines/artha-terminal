"""
ARTHA Terminal - daily F&O one-shot (for Windows Task Scheduler)

Ensures TradingView Desktop is up on CDP, then runs the F&O game-plan job
(compute → snapshot → draw levels). Designed to be fired once each morning.

Timezone handling: this machine runs on US Eastern but the target is 08:00 IST.
The scheduled task fires at a fixed LOCAL time (~22:00 ET → ~07:30–08:30 IST
across DST); this script gates on IST so it's correct regardless:
  • skips IST weekends,
  • runs at most once per IST calendar day (marker file),
so the exact local trigger minute and US daylight-saving shifts don't matter.
"""

import os
import sys
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

_ROOT = Path(__file__).resolve().parent.parent
os.chdir(_ROOT)                     # relative db/ paths resolve regardless of caller CWD
sys.path.insert(0, str(_ROOT))

from config import config


def main() -> int:
    now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
    today = now_ist.date().isoformat()

    if now_ist.weekday() >= 5:       # 5=Sat, 6=Sun (IST)
        print(f"[fno_daily] {today} is an IST weekend — skipping.")
        return 0

    marker = config.db_path.parent / "fno_plans" / "last_run_ist.txt"
    marker.parent.mkdir(parents=True, exist_ok=True)
    if marker.exists() and marker.read_text(encoding="utf-8").strip() == today:
        print(f"[fno_daily] already ran for {today} IST — skipping.")
        return 0

    # Best-effort: bring TradingView up on CDP so the draw is live (not dry-run).
    try:
        from services.tradingview_bridge import ensure_running
        tv = ensure_running()
        print(f"[fno_daily] TradingView ready: {tv}")
    except Exception as e:
        print(f"[fno_daily] TradingView launch skipped ({e}) — draw will dry-run.")

    from ingestion.scheduler import fno_runner
    result = fno_runner()
    print(f"[fno_daily] {today} IST result: {result}")

    marker.write_text(today, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
