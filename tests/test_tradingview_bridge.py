"""Checks for the TradingView draw bridge (pure command build + dry-run)."""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import tradingview_bridge as tv

_LEVELS = [
    {"label": "Max Pain", "price": 24000.0, "kind": "maxpain"},
    {"label": "Call OI Wall (R)", "price": 25000.0, "kind": "resistance"},
    {"label": "Put OI Wall (S)", "price": 23000.0, "kind": "support"},
]


def test_symbol_mapping():
    assert tv.tv_symbol("nifty50") == "NSE:NIFTY"
    assert tv.tv_symbol("banknifty") == "NSE:BANKNIFTY"
    assert tv.tv_symbol("sensex") == "BSE:SENSEX"
    assert tv.tv_symbol("unknown") is None


def test_build_commands_shape_and_order():
    cmds = tv.build_commands("nifty50", _LEVELS)

    # first command sets the symbol and is critical
    assert cmds[0]["argv"] == ["symbol", "NSE:NIFTY"]
    assert cmds[0]["critical"] is True
    # never a destructive full clear — refresh is done via tracked-ID removal
    assert all(c["argv"][:2] != ["draw", "clear"] for c in cmds)
    # one draw-shape per level, horizontal_line at the price, tagged + coloured
    shapes = [c for c in cmds if c["argv"][:2] == ["draw", "shape"]]
    assert len(shapes) == 3
    first = shapes[0]["argv"]
    assert "--type" in first and first[first.index("--type") + 1] == "horizontal_line"
    assert first[first.index("--price") + 1] == "24000"
    # both price and time are required by the tradingview-mcp draw API
    assert "--time" in first and int(first[first.index("--time") + 1]) > 0
    assert first[first.index("--text") + 1].startswith("ARTHA")
    # colour is inside the --overrides JSON (linecolor), not a --color flag
    assert "--color" not in first
    overrides = json.loads(first[first.index("--overrides") + 1])
    assert overrides["linecolor"] == "#FF2E86"                   # maxpain -> laser
    assert overrides["linewidth"] == 2


def test_drawn_ids_roundtrip():
    # the tracked-ID refresh persists the IDs we created, then reads them back
    tv._save_ids("nifty50", ["uiEaL8", "k7UWQk"])
    assert tv._load_prev_ids("nifty50") == ["uiEaL8", "k7UWQk"]
    tv._save_ids("nifty50", [])           # empty overwrites cleanly
    assert tv._load_prev_ids("nifty50") == []
    assert tv._load_prev_ids("never-saved-index") == []


def test_dry_run_writes_artifact():
    # No `tv` CLI on the test box → dry-run path, must not raise, writes artifact.
    os.environ["ARTHA_TV_CLI"] = "definitely-not-a-real-binary-xyz"
    try:
        rep = tv.draw_levels("banknifty", _LEVELS)
    finally:
        os.environ.pop("ARTHA_TV_CLI", None)

    assert rep["ok"] is True and rep["mode"] == "dry-run"
    assert rep["symbol"] == "NSE:BANKNIFTY" and rep["levels"] == 3
    art = Path(rep["artifact"])
    assert art.exists()
    saved = json.loads(art.read_text(encoding="utf-8"))
    assert saved["symbol"] == "NSE:BANKNIFTY"
    assert len(saved["levels"]) == 3 and len(saved["commands"]) >= 4


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"OK — {name}")
