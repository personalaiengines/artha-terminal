"""
ARTHA Terminal - on-demand F&O draw (run on the HOST, not in Docker).

Draws the current levels for one index (or all three) onto TradingView Desktop.
TradingView must be up with the CDP debug port — use the "TradingView (Debug)"
shortcut, or it auto-launches here via ensure_running().

Usage:
    venv\\Scripts\\python.exe scripts\\draw_now.py            # all three
    venv\\Scripts\\python.exe scripts\\draw_now.py nifty50    # one index
"""

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
os.chdir(_ROOT)
sys.path.insert(0, str(_ROOT))

from services.fno_service import build_game_plan, INDEXES, INDEX_NAMES
from services.tradingview_bridge import ensure_running, draw_levels


def _draw(index: str) -> None:
    plan = build_game_plan(index)
    if not plan.get("ok"):
        print(f"  {INDEX_NAMES.get(index, index)}: FAILED — {plan.get('error')}")
        return
    rep = draw_levels(index, plan["levels"])
    if rep.get("mode") == "live":
        print(f"  {INDEX_NAMES.get(index, index)} ({rep['symbol']}): drew {rep.get('drawn', 0)}"
              f", removed {rep.get('removed_previous', 0)} previous")
    else:
        print(f"  {INDEX_NAMES.get(index, index)}: {rep.get('mode')} — {rep.get('note', '')}")


def main() -> int:
    arg = (sys.argv[1] if len(sys.argv) > 1 else "all").lower()
    targets = list(INDEXES) if arg in ("all", "") else [arg]
    if arg not in ("all", "") and arg not in INDEXES:
        print(f"unknown index '{arg}'. Choose: {', '.join(INDEXES)} or 'all'.")
        return 2

    print("Ensuring TradingView is up on CDP…")
    tv = ensure_running()
    if not tv.get("ok"):
        print(f"  TradingView not reachable ({tv.get('error')}). "
              f"Open it via the 'TradingView (Debug)' shortcut and retry.")
    for idx in targets:
        _draw(idx)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
