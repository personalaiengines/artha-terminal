"""
ARTHA Terminal - TradingView draw bridge
Push the daily F&O levels onto the TradingView Desktop chart, headlessly, via the
tradingview-mcp CLI (Chrome DevTools Protocol on localhost:9222).

One-time setup (on the machine running ARTHA):
  1) git clone https://github.com/tradesdontlie/tradingview-mcp
     cd tradingview-mcp && npm install && npm link      # provides the `tv` CLI
     (or set env ARTHA_TV_CLI="node /abs/path/tradingview-mcp/src/cli/index.js")
  2) Launch TradingView Desktop with:  --remote-debugging-port=9222

Behaviour:
  • If the `tv` CLI + TV are reachable → draws horizontal lines for each level.
  • Otherwise → DRY-RUN: writes the draw plan + the exact commands to a JSON
    artifact and returns a report. The daily job never crashes on a missing setup.

Safety: we NEVER `draw clear` your whole chart by default (that would wipe your
own drawings). Lines are tagged "ARTHA · …"; set ARTHA_TV_CLEAR=1 to also clear.

NOTE: the tradingview-mcp README documents `draw_shape → horizontal_line` but not
the exact CLI flags. `_shape_argv()` isolates that one uncertain seam — if your
`tv draw shape --help` differs, fix it there only.
"""

from __future__ import annotations

import os
import json
import time
import shlex
import shutil
import subprocess
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

from config import config

# ARTHA index key -> TradingView chart symbol
_TV_SYMBOL = {
    "nifty50": "NSE:NIFTY",
    "banknifty": "NSE:BANKNIFTY",
    "sensex": "BSE:SENSEX",
}

# level kind -> line colour (hex, matches the ARTHA palette)
_KIND_COLOR = {
    "resistance": "#FF3B4E",   # flare
    "support": "#21F3A0",      # surge
    "maxpain": "#FF2E86",      # laser
    "range": "#FFD84D",        # volt
    "pivot": "#7C8BB8",        # haze
}
_DEFAULT_COLOR = "#7C8BB8"
_TAG = "ARTHA"

_ARTIFACT_DIR = config.db_path.parent / "tv_draw_plans"


def tv_symbol(index: str) -> str | None:
    return _TV_SYMBOL.get(index)


def _cli_base() -> list[str]:
    """The `tv` CLI invocation (overridable via ARTHA_TV_CLI)."""
    return shlex.split(os.getenv("ARTHA_TV_CLI", "tv"))


def _cli_available(base: list[str]) -> bool:
    """True if the CLI binary resolves (does not guarantee TV is up)."""
    if not base:
        return False
    exe = base[0]
    if shutil.which(exe):
        return True
    # `node /path/script.js` form — check node + the script path exist
    return exe.lower() in ("node", "node.exe") and len(base) > 1 and os.path.exists(base[1])


def _shape_argv(price: float, label: str, color: str) -> list[str]:
    """
    Build the `draw shape` args for one horizontal line at `price`.

    Schema confirmed against tradingview-mcp src (core/drawing.js): draw shape
    needs BOTH --price and --time (createShape requires a finite time even for a
    horizontal line — the anchor is irrelevant, the line spans all time), and
    colour/label styling go through --overrides JSON (linecolor/showLabel/…),
    NOT a --color flag.
    """
    overrides = json.dumps({
        "linecolor": color,
        "linewidth": 2,
        "linestyle": 0,          # 0 solid, 1 dotted, 2 dashed
        "textcolor": color,
        "showPrice": True,
    })
    return [
        "draw", "shape",
        "--type", "horizontal_line",
        "--price", f"{price:g}",
        "--time", str(int(time.time())),
        "--text", f"{_TAG} · {label}",
        "--overrides", overrides,
    ]


def status() -> dict:
    """`tv status` — CDP connection health. {'success': bool, ...} or error."""
    ok, out, err = _run(_cli_base() + ["status"], timeout=40.0)
    try:
        return json.loads(out) if out.strip() else {"success": False, "error": err[:200]}
    except Exception:
        return {"success": ok, "raw": (out or err)[:300]}


def launch() -> dict:
    """`tv launch` — start TradingView Desktop with CDP (MSIX-aware, copy-fallback)."""
    ok, out, err = _run(_cli_base() + ["launch"], timeout=180.0)
    try:
        return json.loads(out) if out.strip() else {"success": ok, "error": err[:200]}
    except Exception:
        return {"success": ok, "raw": (out or err)[:300]}


def ensure_running(wait_s: float = 60.0) -> dict:
    """
    Ensure TV is up on CDP: quick status, else launch and poll until ready.

    Note: launching a GUI app's debug port only works from an interactive desktop
    session — so this must run in the logged-in user's session (a logon Startup
    entry or an Interactive scheduled task), never a headless/service context.
    """
    st = status()
    if st.get("success"):
        return {"ok": True, "already": True}
    lr = launch()
    deadline = time.time() + wait_s
    while time.time() < deadline:
        time.sleep(4)
        if status().get("success"):
            return {"ok": True, "launched": True}
    return {"ok": False, "launch": lr, "error": "TV did not report CDP-ready in time"}


def build_commands(index: str, levels: list[dict]) -> list[dict]:
    """
    Pure: the ordered CLI commands (argv without the cli base) to draw `levels`
    on `index`'s chart. Each item: {desc, argv, critical}.
    """
    sym = _TV_SYMBOL.get(index)
    if not sym:
        return []
    cmds: list[dict] = [
        {"desc": f"set symbol {sym}", "argv": ["symbol", sym], "critical": True},
    ]
    for lv in levels:
        price = lv.get("price")
        if price is None:
            continue
        color = _KIND_COLOR.get(lv.get("kind"), _DEFAULT_COLOR)
        cmds.append({
            "desc": f"{lv.get('label')} @ {price:g}",
            "argv": _shape_argv(price, lv.get("label", ""), color),
            "critical": False,
        })
    return cmds


def _run(argv: list[str], timeout: float = 20.0) -> tuple[bool, str, str]:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return p.returncode == 0, p.stdout, p.stderr
    except Exception as e:
        return False, "", str(e)


# --- ARTHA-drawn line tracking (so daily runs refresh, not pile up) ---------
# We remember the entity IDs of the lines WE create per index and remove exactly
# those on the next run. This only ever touches ARTHA's own drawings — the user's
# manual drawings are never listed or removed.

def _ids_file(index: str):
    return _ARTIFACT_DIR / f"{index}_drawn_ids.json"


def _load_prev_ids(index: str) -> list[str]:
    try:
        f = _ids_file(index)
        if f.exists():
            return json.loads(f.read_text(encoding="utf-8")).get("ids", []) or []
    except Exception:
        pass
    return []


def _save_ids(index: str, ids: list[str]) -> None:
    try:
        _ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        _ids_file(index).write_text(
            json.dumps({"ids": ids,
                        "saved_ist": datetime.now(ZoneInfo("Asia/Kolkata")).isoformat()}),
            encoding="utf-8",
        )
    except Exception:
        pass


def _remove_ids(base: list[str], ids: list[str]) -> int:
    """Remove the given shape IDs (best-effort; a missing ID is a harmless no-op)."""
    removed = 0
    for sid in ids:
        ok, out, _err = _run(base + ["draw", "remove", sid])
        if not ok:
            continue
        try:
            if json.loads(out or "{}").get("removed"):
                removed += 1
        except Exception:
            pass
    return removed


def _write_artifact(index: str, sym: str, levels: list[dict], cmds: list[dict]) -> str:
    _ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    date = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
    path = _ARTIFACT_DIR / f"{index}_{date}.json"
    payload = {
        "index": index, "symbol": sym, "date": date,
        "levels": levels,
        "commands": [" ".join(shlex.quote(a) for a in c["argv"]) for c in cmds],
        "generated_ist": datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return str(path)


def draw_levels(index: str, levels: list[dict], *, execute: bool = True) -> dict:
    """
    Draw `levels` on `index`'s TradingView chart (or dry-run).

    Returns a report {ok, mode, symbol, levels, artifact, ...}. Always writes the
    draw-plan artifact; only executes when the CLI resolves and execute=True.
    """
    sym = _TV_SYMBOL.get(index)
    if not sym:
        return {"ok": False, "error": f"no TradingView symbol for '{index}'"}
    if not levels:
        return {"ok": False, "error": "no levels to draw", "symbol": sym}

    cmds = build_commands(index, levels)
    artifact = _write_artifact(index, sym, levels, cmds)

    base = _cli_base()
    if not (execute and _cli_available(base)):
        return {
            "ok": True, "mode": "dry-run", "symbol": sym, "levels": len(levels),
            "artifact": artifact,
            "commands": [" ".join(c["argv"]) for c in cmds],
            "note": "tv CLI not found (or execute=False) — wrote the plan, drew nothing. "
                    "Install tradingview-mcp + launch TradingView with --remote-debugging-port=9222.",
        }

    # Refresh, don't pile up: remove the lines WE drew last time (never the
    # user's own drawings), then draw the fresh set and remember the new IDs.
    removed = _remove_ids(base, _load_prev_ids(index))

    results = []
    new_ids: list[str] = []
    for c in cmds:
        ok, out, err = _run(base + c["argv"])
        entry = {"step": c["desc"], "ok": ok, "err": (err or "").strip()[:200]}
        if ok and c["argv"][:2] == ["draw", "shape"]:
            try:
                eid = json.loads(out or "{}").get("entity_id")
                if eid:
                    new_ids.append(eid)
                    entry["entity_id"] = eid
            except Exception:
                pass
        results.append(entry)
        if not ok and c.get("critical"):
            break

    _save_ids(index, new_ids)
    # A draw command may have left the render loop paused — resume it so the
    # live chart keeps ticking. Best-effort; never fails the draw.
    thaw = unfreeze()
    drew = all(r["ok"] for r in results)
    return {
        "ok": drew, "mode": "live", "symbol": sym, "levels": len(levels),
        "removed_previous": removed, "drawn": len(new_ids),
        "unfreeze": thaw,
        "artifact": artifact, "results": results,
    }


def _cdp_port() -> int:
    try:
        return int(os.getenv("ARTHA_TV_CDP_PORT", "9222"))
    except ValueError:
        return 9222


def unfreeze() -> dict:
    """
    Un-stick a live chart the CDP automation left PAUSED.

    A `tv` (tradingview-mcp) command that enabled the V8 Debugger and paused —
    or died mid-pause — halts the page's JS loop: no requestAnimationFrame, no
    websocket-tick rendering → candles freeze even though data still arrives.
    Detaching resumes V8, so we open a fresh CDP session per page target and send
    Debugger.enable + Debugger.resume (best-effort; a not-paused target errors
    harmlessly). Independent of the `tv` CLI — talks CDP (port 9222) directly.
    """
    from websocket import create_connection  # websocket-client, already vendored

    port = _cdp_port()
    try:
        raw = urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=3).read()
        targets = json.loads(raw)
    except Exception as e:
        return {"ok": False, "error": f"CDP not reachable on :{port} ({e})"}

    resumed = 0
    for t in targets:
        if t.get("type") != "page" or not t.get("webSocketDebuggerUrl"):
            continue
        try:
            ws = create_connection(t["webSocketDebuggerUrl"], timeout=3)
            try:
                ws.send(json.dumps({"id": 1, "method": "Debugger.enable"}))
                ws.recv()
                ws.send(json.dumps({"id": 2, "method": "Debugger.resume"}))
                out = ws.recv()
                # resume succeeds (no "error") only when it WAS paused
                if '"error"' not in out:
                    resumed += 1
            finally:
                ws.close()
        except Exception:
            continue
    return {"ok": True, "resumed": resumed, "targets": len(targets)}


def clear_artha_lines() -> dict:
    """
    Remove ALL ARTHA-tagged lines on the current chart (tag-based: reads each
    shape's text and only removes those starting with 'ARTHA'). Your own drawings
    are never touched. Use this occasionally to clean up orphans — e.g. lines
    drawn before ID-tracking, or if the tracked-ID file was lost. Live-only.
    """
    base = _cli_base()
    if not _cli_available(base):
        return {"ok": False, "error": "tv CLI not found"}
    ok, out, err = _run(base + ["draw", "list"])
    try:
        shapes = json.loads(out or "{}").get("shapes", [])
    except Exception:
        return {"ok": False, "error": f"draw list failed: {(err or out)[:120]}"}
    removed = 0
    for s in shapes:
        _ok, gout, _e = _run(base + ["draw", "get", s.get("id", "")])
        try:
            text = json.loads(gout or "{}").get("properties", {}).get("text", "")
        except Exception:
            text = ""
        if str(text).startswith(_TAG):
            _run(base + ["draw", "remove", s["id"]])
            removed += 1
    return {"ok": True, "removed": removed, "scanned": len(shapes)}


__all__ = ["draw_levels", "build_commands", "tv_symbol", "status", "launch",
           "ensure_running", "clear_artha_lines", "unfreeze"]
