"""
ARTHA Terminal - NIFTY 50 constituents
Curated symbol -> sector map for the NIFTY 50, used for market-breadth.

The NSE live index-constituents API is unreliable (frequent timeouts), so this
list is maintained here and priced via yfinance. Membership is reviewed by NSE
roughly twice a year — verify against
https://www.niftyindices.com/indices/equity/broad-based-indices/NIFTY-50
if the composition looks stale.
"""

# symbol (NSE) -> sector
NIFTY50: dict[str, str] = {
    # Financial Services
    "HDFCBANK": "Financial Services",
    "ICICIBANK": "Financial Services",
    "SBIN": "Financial Services",
    "KOTAKBANK": "Financial Services",
    "AXISBANK": "Financial Services",
    "BAJFINANCE": "Financial Services",
    "BAJAJFINSV": "Financial Services",
    "HDFCLIFE": "Financial Services",
    "SBILIFE": "Financial Services",
    "SHRIRAMFIN": "Financial Services",
    "JIOFIN": "Financial Services",
    # IT
    "TCS": "IT",
    "INFY": "IT",
    "HCLTECH": "IT",
    "WIPRO": "IT",
    "TECHM": "IT",
    "LTIM": "IT",
    # Energy / Oil & Gas / Power
    "RELIANCE": "Energy",
    "ONGC": "Energy",
    "COALINDIA": "Energy",
    "BPCL": "Energy",
    "NTPC": "Energy",
    "POWERGRID": "Energy",
    # Automobile
    "MARUTI": "Automobile",
    "M&M": "Automobile",
    "TMPV": "Automobile",  # Tata Motors (post-2025 demerger; old TATAMOTORS delisted)
    "BAJAJ-AUTO": "Automobile",
    "EICHERMOT": "Automobile",
    "HEROMOTOCO": "Automobile",
    # FMCG
    "HINDUNILVR": "FMCG",
    "ITC": "FMCG",
    "NESTLEIND": "FMCG",
    "BRITANNIA": "FMCG",
    "TATACONSUM": "FMCG",
    # Metals
    "TATASTEEL": "Metals",
    "JSWSTEEL": "Metals",
    "HINDALCO": "Metals",
    # Pharma / Healthcare
    "SUNPHARMA": "Pharma",
    "DRREDDY": "Pharma",
    "CIPLA": "Pharma",
    "APOLLOHOSP": "Healthcare",
    # Construction / Cement
    "LT": "Construction",
    "ULTRACEMCO": "Cement",
    "GRASIM": "Cement",
    # Consumer
    "TITAN": "Consumer",
    "ASIANPAINT": "Consumer",
    "TRENT": "Consumer",
    # Telecom
    "BHARTIARTL": "Telecom",
    # Infra / Diversified
    "ADANIPORTS": "Infrastructure",
    "ADANIENT": "Infrastructure",
}


# NIFTY Next 50 + a few liquid mid-caps (e.g. FEDERALBNK) so the "top
# gainers/losers" universe is broad enough to match NSE's market-wide list,
# not just the 50 largest names. Priced via yfinance; bad tickers are skipped.
NIFTY_NEXT_50: list[str] = [
    "ABB", "ADANIENSOL", "ADANIGREEN", "ADANIPOWER", "ATGL", "AMBUJACEM",
    "DMART", "BAJAJHLDNG", "BANKBARODA", "BEL", "BOSCHLTD", "CANBK",
    "CGPOWER", "CHOLAFIN", "COLPAL", "DABUR", "DIVISLAB", "DLF", "GAIL",
    "GODREJCP", "HAVELLS", "HAL", "ICICIGI", "ICICIPRULI", "INDIGO", "IOC",
    "IRFC", "JINDALSTEL", "JSWENERGY", "LICI", "LODHA", "LTIM", "MANKIND",
    "MOTHERSON", "NAUKRI", "PIDILITIND", "PNB", "RECLTD", "SIEMENS", "SRF",
    "TATAPOWER", "TORNTPHARM", "TVSMOTOR", "UNITDSPR", "VBL", "VEDL",
    "ZOMATO", "ZYDUSLIFE", "IRCTC", "MAXHEALTH",
]

# A handful of additional widely-traded mid-caps that frequently top the
# market gainer/loser lists but sit outside the NIFTY 100.
EXTRA_LIQUID: list[str] = [
    "FEDERALBNK", "IDFCFIRSTB", "AUBANK", "BANDHANBNK", "YESBANK", "RBLBANK",
    "INDHOTEL", "PERSISTENT", "COFORGE", "MPHASIS", "OFSS", "POLYCAB",
    "ASTRAL", "PAGEIND", "PETRONET", "OIL", "NMDC", "SAIL", "NATIONALUM",
    "ASHOKLEY", "BHEL", "IRB", "GMRAIRPORT", "SUZLON", "IDEA", "YESBANK",
    "PFC", "MUTHOOTFIN", "LTF", "AUROPHARMA", "LUPIN", "BIOCON", "GLENMARK",
    "MARICO", "GODREJIND", "BALKRISIND", "MRF", "ESCORTS", "CUMMINSIND",
    "ABCAPITAL", "APLAPOLLO", "DIXON", "KPITTECH", "TATACOMM", "INDUSTOWER",
]


def constituents() -> dict[str, str]:
    """Return the symbol -> sector map."""
    return dict(NIFTY50)


def broad_universe() -> list[str]:
    """De-duplicated broad NSE universe (NIFTY 100 + liquid mid-caps) for movers."""
    seen: dict[str, None] = {}
    for s in list(NIFTY50.keys()) + NIFTY_NEXT_50 + EXTRA_LIQUID:
        seen.setdefault(s, None)
    return list(seen.keys())


__all__ = ["NIFTY50", "NIFTY_NEXT_50", "EXTRA_LIQUID", "constituents", "broad_universe"]
