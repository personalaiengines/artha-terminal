"""Exercise every AI path end to end against the running container, and time it.

Usage: python scripts/ai_check.py   (needs the api container up)

Hits [::1] so it reaches the Docker container, not the stray host uvicorn on
127.0.0.1 (Python resolves localhost to ::1 first, but be explicit).

Checks each answer for the failure modes the grounding rules exist to prevent:
fabricated intraday ranges, invented broker sources, refusal to use live data.
"""

import json
import re
import time
import urllib.error
import urllib.request

API = "http://[::1]:8000"


def call(path, payload=None, timeout=300):
    t0 = time.monotonic()
    try:
        if payload is None:
            req = urllib.request.Request(API + path)
        else:
            req = urllib.request.Request(
                API + path, data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode()
        secs = time.monotonic() - t0
        try:
            return json.loads(raw), secs, None
        except json.JSONDecodeError:
            return raw, secs, None
    except Exception as e:
        return None, time.monotonic() - t0, f"{type(e).__name__}: {e}"


def stream(path, payload, timeout=300):
    """SSE / chunked stream -> (full_text, seconds, first_byte_seconds)."""
    t0 = time.monotonic()
    first = None
    chunks = []
    req = urllib.request.Request(
        API + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            for line in r:
                if first is None:
                    first = time.monotonic() - t0
                chunks.append(line.decode(errors="replace"))
    except Exception as e:
        return "".join(chunks), time.monotonic() - t0, first, f"{type(e).__name__}: {e}"
    return "".join(chunks), time.monotonic() - t0, first, None


# Fabrication tells the grounding contract is supposed to prevent.
BAD = [
    (r"kotak neo|zerodha kite|angel one terminal|bloomberg terminal", "invented broker source"),
    (r"cannot access real-?time|don't have access to (live|real-?time)|"
     r"as an AI (language )?model|I do not have real-?time", "denies having live data"),
    (r"traded in a range of", "fabricated intraday range"),
]


def audit(text):
    if not text:
        return ["EMPTY ANSWER"]
    low = text.lower()
    return [why for rx, why in BAD if re.search(rx, low)]


def show(label, secs, text, extra=""):
    flags = audit(text)
    status = "FAIL " + "; ".join(flags) if flags else "ok"
    n = len(text or "")
    print(f"  {label:<34} {secs:6.1f}s  {n:>6}ch  {status}{extra}")
    return not flags


def main():
    print("=" * 78)
    print("AI PATHS")
    print("=" * 78)
    ok = True

    # 1. Non-streaming analyst, several intents.
    questions = [
        ("lookup", "What is TCS trading at?"),
        ("screen", "Show me pharma stocks"),
        ("compare", "Compare TCS vs Infosys"),
        ("market", "How did the Indian market do today?"),
        ("deep", "Do a deep dive on RELIANCE"),
    ]
    for intent, q in questions:
        body, secs, err = call("/api/ai", {"q": q})
        if err:
            print(f"  {intent:<34} {secs:6.1f}s  ERROR {err}")
            ok = False
            continue
        text = (body or {}).get("answer") or (body or {}).get("markdown") or ""
        ok &= show(f"/api/ai {intent}", secs, text,
                   extra=f"  intent={(body or {}).get('intent')}")

    # 2. Streaming analyst (what the AI Analyst page actually uses).
    text, secs, first, err = stream("/api/ai/stream", {"q": "What is TCS trading at?"})
    if err:
        print(f"  {'/api/ai/stream':<34} {secs:6.1f}s  ERROR {err}")
        ok = False
    else:
        ok &= show("/api/ai/stream", secs, text, extra=f"  first byte {first:.1f}s")

    # 3. Every service that runs a prompt.
    print()
    print("=" * 78)
    print("SERVICE PROMPTS (breadth strategist read has no live endpoint - archive only)")
    print("=" * 78)
    svc = [
        ("/api/brief", "brief", 300),
        ("/api/news", "items", 300),
        ("/api/events", "events", 300),
        ("/api/stock/RELIANCE/analysis", "markdown", 300),
        ("/api/fno/nifty50/narrative", "markdown", 300),
    ]
    for path, key, tmo in svc:
        body, secs, err = call(path, timeout=tmo)
        if err:
            print(f"  {path:<34} {secs:6.1f}s  ERROR {err}")
            ok = False
            continue
        src = (body or {}).get("data") if isinstance((body or {}).get("data"), dict) else (body or {})
        val = src.get(key)
        if isinstance(val, dict):
            text = val.get("markdown") or val.get("text") or json.dumps(val)[:400]
        elif isinstance(val, list):
            text = json.dumps(val)[:400]
            print(f"  {path:<34} {secs:6.1f}s  {len(val):>6} items ok")
            continue
        else:
            text = val or ""
        ok &= show(path, secs, text)

    print()
    print("AI paths all clean" if ok else "AI paths: FAILURES ABOVE")
    return ok


if __name__ == "__main__":
    main()
