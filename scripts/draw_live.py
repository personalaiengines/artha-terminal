"""
ARTHA Terminal - LIVE F&O draw loop (run on the HOST, not in Docker).

Keeps the option-derived levels (max pain, OI walls, expected-move band) fresh on
the TradingView chart while the market moves — rebuilds the plan and redraws every
ARTHA_DRAW_INTERVAL seconds during IST market hours. draw_levels already refreshes
(removes our previous lines, draws the new set) and unfreezes the render loop, so
the chart keeps ticking live.

Static pivots (prior-day OHLC) don't change intraday — they just get redrawn to
the same price; only the option-derived levels actually move.

Usage:
    venv\\Scripts\\python.exe scripts\\draw_live.py            # all three, live
    venv\\Scripts\\python.exe scripts\\draw_live.py nifty50    # one index
    venv\\Scripts\\python.exe scripts\\draw_live.py --selftest # gate check, no draw

Stop with Ctrl-C.
"""

import os
import sys
import time
from pathlib import Path
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

_ROOT = Path(__file__).resolve().parent.parent
os.chdir(_ROOT)
sys.path.insert(0, str(_ROOT))

_IST = ZoneInfo("Asia/Kolkata")
_OPEN = dtime(9, 15)
_CLOSE = dtime(15, 30)


def in_market_hours(now: datetime) -> bool:
    """True during NSE cash/F&O session: IST weekday, 09:15–15:30 inclusive."""
    if now.weekday() >= 5:            # 5=Sat, 6=Sun
        return False
    return _OPEN <= now.timetz().replace(tzinfo=None) <= _CLOSE


def session_over(now: datetime) -> bool:
    """
    True when today's session can no longer run — so a task launched pre-open can
    exit cleanly after close (one bounded run per day, no second instance piling
    up overnight). Weekend, or a weekday already past 15:30 IST.
    """
    if now.weekday() >= 5:
        return True
    return now.timetz().replace(tzinfo=None) > _CLOSE


def _interval() -> float:
    try:
        return max(15.0, float(os.getenv("ARTHA_DRAW_INTERVAL", "60")))
    except ValueError:
        return 60.0


def _draw(index: str, names: dict) -> None:
    from services.fno_service import build_game_plan
    from services.tradingview_bridge import draw_levels

    plan = build_game_plan(index)
    if not plan.get("ok"):
        print(f"  {names.get(index, index)}: FAILED — {plan.get('error')}")
        return
    rep = draw_levels(index, plan["levels"])
    ts = datetime.now(_IST).strftime("%H:%M:%S")
    if rep.get("mode") == "live":
        thaw = rep.get("unfreeze", {})
        print(f"  [{ts}] {names.get(index, index)} ({rep['symbol']}): drew {rep.get('drawn', 0)}"
              f", removed {rep.get('removed_previous', 0)}, resumed {thaw.get('resumed', 0)}")
    else:
        print(f"  [{ts}] {names.get(index, index)}: {rep.get('mode')} — {rep.get('note', '')}")


def main() -> int:
    arg = (sys.argv[1] if len(sys.argv) > 1 else "all").lower()
    if arg == "--selftest":
        return 0

    from services.fno_service import INDEXES, INDEX_NAMES
    from services.tradingview_bridge import ensure_running

    targets = list(INDEXES) if arg in ("all", "") else [arg]
    if arg not in ("all", "") and arg not in INDEXES:
        print(f"unknown index '{arg}'. Choose: {', '.join(INDEXES)} or 'all'.")
        return 2

    interval = _interval()
    print(f"Ensuring TradingView is up on CDP…")
    tv = ensure_running()
    if not tv.get("ok"):
        print(f"  TradingView not reachable ({tv.get('error')}). "
              f"Open the 'TradingView (Debug)' shortcut and retry.")
        return 1

    print(f"Live draw loop: {', '.join(targets)} every {interval:g}s during IST 09:15–15:30. Ctrl-C to stop.")
    try:
        while True:
            now = datetime.now(_IST)
            if session_over(now):
                print(f"  [{now.strftime('%H:%M:%S')}] IST session over — exiting.")
                return 0
            if in_market_hours(now):
                for idx in targets:
                    _draw(idx, INDEX_NAMES)
            else:
                print(f"  [{now.strftime('%H:%M:%S')}] pre-open (IST) — waiting.")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nstopped.")
        return 0


def _selftest() -> None:
    mk = lambda w, h, m: datetime(2026, 7, 20 + w, h, m, tzinfo=_IST)  # 2026-07-20 = Mon
    assert in_market_hours(mk(0, 9, 15)) is True      # Mon open edge
    assert in_market_hours(mk(0, 15, 30)) is True     # Mon close edge
    assert in_market_hours(mk(0, 9, 14)) is False     # pre-open
    assert in_market_hours(mk(0, 15, 31)) is False    # post-close
    assert in_market_hours(mk(0, 12, 0)) is True      # midday
    assert in_market_hours(mk(5, 12, 0)) is False     # Saturday
    assert session_over(mk(0, 15, 31)) is True         # weekday post-close
    assert session_over(mk(0, 9, 0)) is False          # weekday pre-open
    assert session_over(mk(0, 12, 0)) is False         # weekday midday
    assert session_over(mk(5, 12, 0)) is True          # Saturday
    print("selftest ok")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        _selftest()
        raise SystemExit(0)
    raise SystemExit(main())
