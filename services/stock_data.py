"""
ARTHA Terminal - Live single-stock data (for the Deep-Dive page)

The local DB only holds ~20 symbols, so a search for anything else (e.g. FEDERALBNK)
returned "no data". This service fetches ANY NSE symbol live via yfinance and maps
it into the exact dict shapes the Deep-Dive panels and the red-flag / scorecard
engines already expect (fundamentals / computed_metrics / symbol_master column
names). Upstox supplies the live intraday quote when the market is open.

Everything returned is real: fundamentals from yfinance's info, returns/DMA/RSI
computed from the actual price history. Missing fields are left as None (panels
render "—") rather than faked.
"""

from __future__ import annotations

import warnings
import logging
from datetime import datetime

warnings.filterwarnings("ignore")
logging.getLogger("yfinance").setLevel(logging.CRITICAL)


def _pct(v, scale_if_fraction: bool = True):
    """Normalise a ratio that yfinance may return as a fraction (0.15) or percent (15)."""
    if v is None:
        return None
    try:
        v = float(v)
    except Exception:
        return None
    if scale_if_fraction and -1.5 < v < 1.5:
        return round(v * 100, 2)
    return round(v, 2)


def fundamentals_from_info(sym: str, info: dict) -> dict:
    """Map a yfinance .info payload to the `fundamentals` table's columns.

    Shared by the live per-symbol path (get_live_stock_data) and the batch
    fundamentals ETL so the two can't drift. Kept as a pure mapping — the
    caller owns fetching, which is what makes it reusable for both.
    """
    info = info or {}
    return {
        "symbol": sym,
        "pe_ratio": info.get("trailingPE"),
        "pb_ratio": info.get("priceToBook"),
        "ps_ratio": info.get("priceToSalesTrailing12Months"),
        "ev_ebitda": info.get("enterpriseToEbitda"),
        # yfinance already returns dividendYield as a percent (e.g. 2.05 = 2.05%)
        "dividend_yield": round(float(info["dividendYield"]), 2) if info.get("dividendYield") else None,
        "roe": _pct(info.get("returnOnEquity")),
        "roce": None,
        "roic": None,
        "gross_margin": _pct(info.get("grossMargins")),
        "operating_margin": _pct(info.get("operatingMargins")),
        "net_margin": _pct(info.get("profitMargins")),
        # yfinance debtToEquity is a percentage (e.g. 45.6 => 0.456 ratio)
        "debt_to_equity": round(info["debtToEquity"] / 100, 2) if info.get("debtToEquity") else None,
        "current_ratio": info.get("currentRatio"),
        "quick_ratio": info.get("quickRatio"),
        "interest_coverage": None,
        "revenue_ttm": info.get("totalRevenue"),
        "pat_ttm": info.get("netIncomeToCommon"),
        "book_value": info.get("bookValue"),
        "source": "yfinance-live",
    }


def _returns_from_closes(closes) -> dict:
    """Trailing returns (%) from a daily close series, by trading-day offsets."""
    out = {k: None for k in ("return_1d", "return_1w", "return_1m", "return_3m",
                             "return_6m", "return_1y", "return_3y", "return_5y")}
    offsets = {"return_1d": 1, "return_1w": 5, "return_1m": 21, "return_3m": 63,
               "return_6m": 126, "return_1y": 252, "return_3y": 756, "return_5y": 1260}
    n = len(closes)
    if n < 2:
        return out
    last = closes.iloc[-1]
    for key, off in offsets.items():
        if n > off and closes.iloc[-1 - off]:
            prev = closes.iloc[-1 - off]
            out[key] = round((last / prev - 1) * 100, 2)
    return out


def _rsi_14(closes) -> float | None:
    """Standard 14-period RSI from a close series."""
    if len(closes) < 15:
        return None
    delta = closes.diff().dropna()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    if loss.iloc[-1] == 0:
        return 100.0
    rs = gain.iloc[-1] / loss.iloc[-1]
    return round(100 - 100 / (1 + rs), 2)


def _live_quote(symbol: str) -> dict | None:
    """
    Best-effort Upstox live quote via the ISIN instrument key (empty outside
    market hours). Equities are keyed by ISIN on Upstox, so we resolve it from
    the instrument master first.
    """
    import asyncio

    try:
        from services.instruments import instrument_key
        key = instrument_key(symbol)
    except Exception:
        key = None
    if not key:
        return None

    async def _go():
        from services import UpstoxClient
        return await UpstoxClient().get_quote_by_keys([key])

    try:
        loop = asyncio.new_event_loop()
        try:
            r = loop.run_until_complete(_go())
        finally:
            loop.close()
        if isinstance(r, dict):
            for v in r.values():
                if v.get("last_price"):
                    return v
    except Exception:
        pass
    return None


def _stmt_row(df, *names):
    """First matching, non-empty row from a yfinance statement DataFrame."""
    if df is None or getattr(df, "empty", True):
        return None
    for n in names:
        if n in df.index:
            s = df.loc[n].dropna()
            if len(s):
                return s
    return None


def _red_flag_inputs(tk, info: dict, sector: str | None) -> dict:
    """
    Build the dict the RedFlagEngine expects (de_ratio, ocf, pat, rev_growth,
    recv_growth, interest_coverage, sector) from yfinance financial statements.
    Best-effort — each field is None if the underlying data is missing.
    """
    out = {"sector": sector}
    try:
        cf, inc, bs = tk.cashflow, tk.income_stmt, tk.balance_sheet
    except Exception:
        return out

    ocf = _stmt_row(cf, "Operating Cash Flow", "Total Cash From Operating Activities",
                    "Cash Flow From Continuing Operating Activities")
    out["ocf"] = float(ocf.iloc[0]) if ocf is not None else None

    ni = _stmt_row(inc, "Net Income", "Net Income Common Stockholders",
                   "Net Income From Continuing Operation Net Minority Interest")
    out["pat"] = float(ni.iloc[0]) if ni is not None else None

    td = _stmt_row(bs, "Total Debt")
    eq = _stmt_row(bs, "Stockholders Equity", "Common Stock Equity",
                   "Total Equity Gross Minority Interest")
    if td is not None and eq is not None and eq.iloc[0]:
        out["de_ratio"] = round(float(td.iloc[0]) / float(eq.iloc[0]), 2)
    elif info.get("debtToEquity"):
        out["de_ratio"] = round(info["debtToEquity"] / 100, 2)

    ebit = _stmt_row(inc, "EBIT", "Operating Income")
    ie = _stmt_row(inc, "Interest Expense")
    if ebit is not None and ie is not None and ie.iloc[0]:
        out["interest_coverage"] = round(float(ebit.iloc[0]) / abs(float(ie.iloc[0])), 2)

    rev = _stmt_row(inc, "Total Revenue", "Operating Revenue")
    if rev is not None and len(rev) >= 2 and rev.iloc[1]:
        out["rev_growth"] = round((rev.iloc[0] / rev.iloc[1] - 1) * 100, 2)

    recv = _stmt_row(bs, "Receivables", "Accounts Receivable", "Net Receivables",
                     "Other Receivables", "Gross Accounts Receivable")
    if recv is not None and len(recv) >= 2 and recv.iloc[1]:
        out["recv_growth"] = round((recv.iloc[0] / recv.iloc[1] - 1) * 100, 2)

    return out


def _ownership(tk) -> dict | None:
    """
    Approximate ownership split from yfinance major_holders.
    insiders ≈ promoter, institutions ≈ FII+DII, remainder ≈ public/other.
    """
    try:
        mh = tk.major_holders
    except Exception:
        return None
    if mh is None or getattr(mh, "empty", True):
        return None

    def _v(key):
        try:
            return float(mh.loc[key].iloc[0])
        except Exception:
            return None

    insiders = _v("insidersPercentHeld")
    insts = _v("institutionsPercentHeld")
    if insiders is None and insts is None:
        return None
    promoter = round((insiders or 0) * 100, 2)
    institutions = round((insts or 0) * 100, 2)
    public = round(max(0.0, 100 - promoter - institutions), 2)
    return {"promoter": promoter, "institutions": institutions, "public": public,
            "institutions_count": _v("institutionsCount")}


def get_live_stock_data(symbol: str) -> dict | None:
    """
    Live snapshot for any NSE symbol, shaped like the Deep-Dive DB loader:

        {symbol, master, fundamentals, metrics, shareholding, history (DataFrame),
         latest_close, latest_date, live_quote, holders (DataFrame|None),
         source, ok}

    Returns None if the symbol can't be priced at all (invalid ticker).
    """
    import yfinance as yf
    import pandas as pd
    from db import get_connection

    sym = symbol.strip().upper()
    exchange = "NSE"
    try:
        with get_connection() as conn:
            row = conn.execute("SELECT exchange FROM symbol_master WHERE symbol=?", (sym,)).fetchone()
            if row and row["exchange"]:
                exchange = row["exchange"]
    except Exception:
        pass
    # BSE-only symbols (no NSE listing) need yfinance's .BO suffix instead of .NS.
    suffix = ".NS" if exchange == "NSE" else ".BO"
    tk = yf.Ticker(f"{sym}{suffix}")

    # --- price history (the anchor; if this fails the symbol is unusable) ---
    try:
        hist = tk.history(period="5y", interval="1d", auto_adjust=False)
    except Exception:
        hist = None
    if hist is None or hist.empty:
        return None

    hist = hist.reset_index()
    hist.columns = [str(c).lower() for c in hist.columns]
    # normalise the date column name yfinance may call 'date' or 'index'
    date_col = "date" if "date" in hist.columns else hist.columns[0]
    price_df = pd.DataFrame({
        "date": pd.to_datetime(hist[date_col]).dt.strftime("%Y-%m-%d"),
        "open": hist.get("open"),
        "high": hist.get("high"),
        "low": hist.get("low"),
        "close": hist.get("close"),
        "volume": hist.get("volume"),
    }).dropna(subset=["close"])

    closes = price_df["close"].reset_index(drop=True)
    latest_close = round(float(closes.iloc[-1]), 2)
    latest_date = price_df["date"].iloc[-1]

    # --- fundamentals via .info (best-effort; .info is flaky under rate limits) ---
    info = {}
    for _ in range(2):
        try:
            info = tk.info or {}
        except Exception:
            info = {}
        if info.get("longName") or info.get("trailingPE"):
            break

    fundamentals = fundamentals_from_info(sym, info)

    # --- computed metrics from the real history ---
    dma_50 = round(float(closes.tail(50).mean()), 2) if len(closes) >= 50 else info.get("fiftyDayAverage")
    dma_200 = round(float(closes.tail(200).mean()), 2) if len(closes) >= 200 else info.get("twoHundredDayAverage")
    ath = round(float(price_df["high"].max()), 2) if "high" in price_df else None
    atl = round(float(price_df["low"].min()), 2) if "low" in price_df else None
    metrics = {
        "symbol": sym,
        "dma_50": dma_50,
        "dma_200": dma_200,
        "rsi_14": _rsi_14(closes),
        "beta": info.get("beta"),
        "ath": ath,
        "atl": atl,
        "distance_from_ath": round((latest_close / ath - 1) * 100, 2) if ath else None,
        "distance_from_atl": round((latest_close / atl - 1) * 100, 2) if atl else None,
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        **_returns_from_closes(closes),
    }

    master = {
        "symbol": sym,
        "company_name": info.get("longName") or info.get("shortName") or sym,
        "isin": info.get("isin"),
        "exchange": exchange,
        "industry": info.get("industry"),
        "sector": info.get("sector") or "—",
        "market_cap_cr": round(info["marketCap"] / 1e7, 1) if info.get("marketCap") else None,
    }

    # --- holders (yfinance sometimes exposes institutional / major holders) ---
    holders = None
    try:
        ih = tk.institutional_holders
        if ih is not None and not ih.empty:
            holders = ih
    except Exception:
        holders = None

    # --- red-flag engine inputs + ownership split (from financial statements) ---
    try:
        rf_inputs = _red_flag_inputs(tk, info, info.get("sector"))
    except Exception:
        rf_inputs = {"sector": info.get("sector")}
    try:
        ownership = _ownership(tk)
    except Exception:
        ownership = None

    return {
        "symbol": sym,
        "master": master,
        "fundamentals": fundamentals,
        "metrics": metrics,
        "red_flag_inputs": rf_inputs,
        "ownership": ownership,
        "shareholding": [],          # quarterly promoter/FII/DII not in this source
        "history": price_df,
        "latest_close": latest_close,
        "latest_date": latest_date,
        "live_quote": _live_quote(sym),
        "holders": holders,
        "source": "yfinance-live",
        "generated": datetime.now().isoformat(),
        "ok": True,
    }


# yfinance sector labels -> NSE's own industry labels (index_members.industry)
_SECTOR_TRANSLATE = {
    "Technology": "IT",
    "Consumer Defensive": "FMCG",
    "Consumer Cyclical": "Consumer",
    "Basic Materials": "Metals",
    "Communication Services": "Telecom",
    "Industrials": "Construction",
    "Utilities": "Energy",
}


def get_sector_peers(symbol: str, yf_sector: str | None, metric: str = "return_6m"):
    """
    Same-sector peers vs the analysed stock, compared on 6-month return.

    Peers are drawn from NSE index membership (index_members); returns are computed
    live from a small yfinance batch. Returns a DataFrame [symbol, <metric>]
    (empty if the sector can't be resolved).
    """
    import pandas as pd
    from services.constituents import sector_map
    sectors = sector_map()

    sym = symbol.strip().upper()
    curated = sectors.get(sym) or _SECTOR_TRANSLATE.get(yf_sector or "", yf_sector or "")
    if not curated:
        return pd.DataFrame()

    peers = [s for s, sec in sectors.items() if sec == curated and s != sym]
    peers = peers[:6]
    if sym not in peers:
        peers.append(sym)
    if len(peers) < 2:
        return pd.DataFrame()

    import yfinance as yf
    tickers = [f"{s}.NS" for s in peers]
    try:
        df = yf.download(tickers, period="6mo", interval="1d", progress=False,
                         group_by="ticker", threads=True)
    except Exception:
        return pd.DataFrame()
    if df is None or len(df) == 0:
        return pd.DataFrame()

    rows = []
    for s in peers:
        try:
            closes = df[f"{s}.NS"]["Close"].dropna()
            if len(closes) >= 2 and closes.iloc[0]:
                rows.append({"symbol": s,
                             metric: round((closes.iloc[-1] / closes.iloc[0] - 1) * 100, 2)})
        except Exception:
            continue
    return pd.DataFrame(rows)


__all__ = ["get_live_stock_data", "get_sector_peers"]
