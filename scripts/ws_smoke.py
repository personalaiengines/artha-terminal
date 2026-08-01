"""
Manual smoke test for the /ws endpoint end-to-end (Phase 2 Upstox stream +
Phase 3 Starlette WS endpoint wired together). Not part of the automated
test suite — this needs a running `python -m api.server` with a real
UPSTOX_ACCESS_TOKEN, and market hours (or at least a live index feed) to see
actual ticks.

Usage:
    python -m api.server            # in one terminal
    python scripts/ws_smoke.py      # in another
"""

import asyncio
import json

import websockets


async def main():
    uri = "ws://localhost:8000/ws"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({"action": "subscribe", "keys": ["NSE_INDEX|Nifty 50"]}))
        print(f"Subscribed on {uri}, listening for 30s...")
        try:
            async with asyncio.timeout(30):
                while True:
                    print(await ws.recv())
        except TimeoutError:
            print("Done (30s elapsed).")


if __name__ == "__main__":
    asyncio.run(main())
