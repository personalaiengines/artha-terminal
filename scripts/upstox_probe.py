"""
ARTHA Terminal - Upstox web chart-widget PROBE (analysis, draws nothing).

Answers the one open question blocking "draw R/S on Upstox" (IDEA_FNO_CHART_DRAWING
Option B): does pro.upstox.com expose its embedded TradingView charting-library
widget to JS, so we could call widget.activeChart().createShape(price, ...)?

Setup (once):
  1) Close Chrome fully, then launch it with the debug port:
       chrome.exe --remote-debugging-port=9222 --user-data-dir=%TEMP%\\upstox-cdp
  2) In THAT Chrome, log into https://pro.upstox.com and open an index chart.
  3) Run:  venv\\Scripts\\python.exe scripts\\upstox_probe.py

Reads only. Reports: which globals/iframes look like the TV widget, per frame.
Verdict tells us whether Option B is a thin bridge or a dead end.
"""

import os
import sys
import json
import urllib.request

_PORT = int(os.getenv("ARTHA_TV_CDP_PORT", "9222"))

# JS run in each frame: hunt for a reachable charting-library widget handle.
_PROBE_JS = r"""
(function () {
  var out = { href: location.href, matchKeys: [], iframes: [],
              typeofTvWidget: typeof window.tvWidget,
              typeofTradingView: typeof window.TradingView,
              widgetApiSeen: false, activeChartSeen: false };
  try {
    for (var k in window) {
      try {
        if (/tv|trading|chart|widget/i.test(k)) {
          out.matchKeys.push(k);
          var v = window[k];
          if (v && typeof v.activeChart === "function") out.activeChartSeen = true;
          if (v && typeof v.createShape === "function") out.widgetApiSeen = true;
          if (v && v.activeChart && typeof v.activeChart === "function") {
            try {
              var c = v.activeChart();
              if (c && typeof c.createShape === "function") out.widgetApiSeen = true;
            } catch (e) {}
          }
        }
      } catch (e) {}
    }
    var fr = document.querySelectorAll("iframe");
    for (var i = 0; i < fr.length; i++) out.iframes.push(fr[i].src || fr[i].id || "(inline)");
  } catch (e) { out.error = String(e); }
  return JSON.stringify(out);
})()
"""


def _targets():
    raw = urllib.request.urlopen(f"http://127.0.0.1:{_PORT}/json", timeout=3).read()
    return json.loads(raw)


def _eval_all_frames(ws_url: str) -> list[dict]:
    """Runtime.enable, then evaluate the probe in EVERY execution context (frames)."""
    from websocket import create_connection

    ws = create_connection(ws_url, timeout=5)
    results = []
    try:
        ws.send(json.dumps({"id": 1, "method": "Runtime.enable"}))
        # Collect executionContextCreated events for a moment, then eval in each.
        ctx_ids = [None]  # None = default/top context
        ws.settimeout(2.0)
        try:
            while True:
                msg = json.loads(ws.recv())
                if msg.get("method") == "Runtime.executionContextCreated":
                    cid = msg["params"]["context"]["id"]
                    if cid not in ctx_ids:
                        ctx_ids.append(cid)
        except Exception:
            pass  # timed out draining the event backlog — expected
        ws.settimeout(5.0)
        mid = 100
        for cid in ctx_ids:
            mid += 1
            params = {"expression": _PROBE_JS, "returnByValue": True}
            if cid is not None:
                params["contextId"] = cid
            ws.send(json.dumps({"id": mid, "method": "Runtime.evaluate", "params": params}))
            # read until our id comes back
            for _ in range(30):
                msg = json.loads(ws.recv())
                if msg.get("id") == mid:
                    val = msg.get("result", {}).get("result", {}).get("value")
                    if val:
                        try:
                            results.append(json.loads(val))
                        except Exception:
                            pass
                    break
    finally:
        ws.close()
    return results


def main() -> int:
    try:
        targets = _targets()
    except Exception as e:
        print(f"CDP not reachable on :{_PORT} ({e}).")
        print("Launch Chrome with --remote-debugging-port=9222 and open pro.upstox.com first.")
        return 1

    pages = [t for t in targets if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
    upstox = [t for t in pages if "upstox" in (t.get("url") or "").lower()]
    if not upstox:
        print(f"No pro.upstox.com tab found among {len(pages)} page targets. Open an Upstox chart.")
        for t in pages:
            print(f"  - {t.get('url')}")
        return 2

    hit = False
    for t in upstox:
        print(f"\n=== {t.get('url')} ===")
        for r in _eval_all_frames(t["webSocketDebuggerUrl"]):
            print(f"  frame: {r.get('href')}")
            print(f"    tvWidget={r.get('typeofTvWidget')}  TradingView={r.get('typeofTradingView')}"
                  f"  createShape={r.get('widgetApiSeen')}  activeChart={r.get('activeChartSeen')}")
            if r.get("matchKeys"):
                print(f"    matching window keys: {', '.join(r['matchKeys'][:25])}")
            if r.get("iframes"):
                print(f"    iframes: {', '.join(r['iframes'][:10])}")
            if r.get("widgetApiSeen"):
                hit = True

    print("\n--- VERDICT ---")
    if hit:
        print("REACHABLE: a widget with createShape() is exposed → Option B is a THIN bridge")
        print("(mirror tradingview_bridge, call activeChart().createShape at each price).")
    else:
        print("NOT reachable on window: widget is closured or iframed away.")
        print("Options left: (a) drive the drawing TOOL via synthetic input + price->pixel from")
        print("the axis (brittle), or (b) skip Option B, use the native ARTHA chart (Option A).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
