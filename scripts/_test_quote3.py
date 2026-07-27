"""Inspect raw Upstox equity quote response structure."""
import sys, asyncio, json, httpx
sys.path.insert(0, "/app")
from config import config


async def test():
    token = config.upstox.analytics_token
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    async with httpx.AsyncClient() as client:
        # Single equity, full quote
        r = await client.get("https://api.upstox.com/v2/market-quote/quotes",
                             headers=headers, params={"symbol": "NSE_EQ|RELIANCE"}, timeout=10.0)
        print("HTTP", r.status_code)
        print(json.dumps(r.json(), indent=2)[:1200])


asyncio.run(test())
