"""Temporary diagnostic: test Upstox API connectivity."""
import sys, asyncio, json
sys.path.insert(0, "/app")
from services.upstox import UpstoxClient


async def test():
    client = UpstoxClient()

    print("=== TEST 1: Live quote via analytics token (1yr) ===")
    try:
        q = await client.get_quote(["NSE:RELIANCE", "NSE:TCS", "NSE:NIFTY 50"])
        if isinstance(q, dict) and "data" in q:
            print("Status: OK")
            for k, v in q["data"]. items():
                print(f"  {k}: last_price={v.get('last_price')}, change={v.get('change')}")
        elif isinstance(q, dict) and "error" in q:
            print("Token not configured:", q["error"][:200])
        else:
            print("Unexpected response:", json.dumps(q)[:300])
    except Exception as e:
        print(f"FAILED: {type(e).__name__}: {str(e)[:300]}")

    print()
    print("=== TEST 2: Holdings via access token (daily) ===")
    try:
        h = await client.get_portfolio_holdings()
        if isinstance(h, dict) and "data" in h:
            rows = h["data"]
            print(f"Status: OK — {len(rows)} holdings")
            for r in rows[:3]:
                print(f"  {r.get('tradingsymbol')}: qty={r.get('quantity')} avg={r.get('average_price')} last={r.get('last_price')}")
        elif isinstance(h, dict) and "error" in h:
            print("Token not configured:", h["error"][:200])
        else:
            # Could be an error envelope from Upstox
            status = h.get("status") if isinstance(h, dict) else None
            print(f"Status: {status}")
            print("Response:", json.dumps(h)[:500])
    except Exception as e:
        print(f"FAILED: {type(e).__name__}: {str(e)[:300]}")


asyncio.run(test())
