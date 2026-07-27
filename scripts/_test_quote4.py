"""Probe multiple Upstox endpoint/formats to pick the reliable one."""
import sys, asyncio, json, httpx
sys.path.insert(0, "/app")
from config import config


async def main():
    token = config.upstox.analytics_token
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    base = "https://api.upstox.com/v2"

    async with httpx.AsyncClient() as c:
        # 1. LTP endpoint for equity
        for sym in ["NSE_EQ|RELIANCE", "BSE_EQ|RELIANCE"]:
            try:
                r = await c.get(f"{base}/market-quote/ltp", headers=headers, params={"symbol": sym}, timeout=10.0)
                print(f"LTP {sym} -> {r.status_code}: {r.text[:200]}")
            except Exception as e:
                print(f"LTP {sym} EXC: {e}")

        # 2. OHLC endpoint
        try:
            r = await c.get(f"{base}/market-quote/ohlc", headers=headers, params={"symbol": "NSE_EQ|RELIANCE"}, timeout=10.0)
            print(f"OHLC NSE_EQ|RELIANCE -> {r.status_code}: {r.text[:300]}")
        except Exception as e:
            print(f"OHLC EXC: {e}")

        # 3. multi-symbol quotes with full key set
        try:
            syms = "NSE_EQ|RELIANCE,NSE_EQ|TCS,NSE_INDEX|Nifty 50,NSE_INDEX|Nifty Bank"
            r = await c.get(f"{base}/market-quote/quotes", headers=headers, params={"symbol": syms}, timeout=10.0)
            d = r.json()
            print("MULTI ->", r.status_code, "keys=", list(d.get("data", {}).keys()))
            for k, v in d.get("data", {}).items():
                print("   ", k, "->", json.dumps(v)[:160])
        except Exception as e:
            print(f"MULTI EXC: {e}")


asyncio.run(main())
