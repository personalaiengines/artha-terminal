"""Test corrected Upstox instrument-key format for live quotes."""
import sys, asyncio, json, httpx
sys.path.insert(0, "/app")
from config import config


async def test():
    token = config.upstox.analytics_token
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    # Upstox v2 uses instrument keys with pipe: NSE_EQ|RELIANCE
    formats = [
        ["NSE_EQ|RELIANCE", "NSE_EQ|TCS"],
        ["NSE_EQ|RELIANCE"],
        ["NSE_INDEX|Nifty 50"],
    ]

    async with httpx.AsyncClient() as client:
        for fmt in formats:
            symbols = ",".join(fmt)
            url = "https://api.upstox.com/v2/market-quote/quotes"
            try:
                r = await client.get(url, headers=headers, params={"symbol": symbols}, timeout=10.0)
                print(f"[{symbols}] -> HTTP {r.status_code}")
                body = r.text[:400]
                if r.status_code == 200:
                    data = r.json()
                    for k, v in data.get("data", {}).items():
                        print(f"    {k}: last_price={v.get('last_price')} ohlc={v.get('ohlc')}")
                else:
                    print("    body:", body)
            except Exception as e:
                print(f"[{symbols}] EXC: {e}")
            print()


asyncio.run(test())
