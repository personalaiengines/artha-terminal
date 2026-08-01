"""
ARTHA Terminal - Upstox API client
Live market data (analytics token) + portfolio (daily access token).

Yahoo Finance fallback lives in services/yahoo.py; search in services/search.py.
"""

import httpx
from datetime import datetime
from urllib.parse import quote
from config import config


# ------------------------------------------------------------------
# Upstox instrument-key helpers
# Upstox v2 uses pipe-delimited instrument keys: "NSE_EQ|RELIANCE",
# "NSE_INDEX|Nifty 50". The quote response echoes them colon-delimited:
# "NSE_INDEX:Nifty 50". We normalize between the two.
# ------------------------------------------------------------------

INDEX_KEYS = {
    "nifty50": "NSE_INDEX|Nifty 50",
    "banknifty": "NSE_INDEX|Nifty Bank",
    "sensex": "BSE_INDEX|SENSEX",
    # "Nifty Midcap 150" is not a valid Upstox instrument key — the quotes
    # endpoint silently omits unknown keys, so this index has always come
    # back empty. "Nifty Midcap 50" is the real key (and maps cleanly to
    # Yahoo's ^NSEMDCP50 for the fallback path).
    "niftymidcap": "NSE_INDEX|Nifty Midcap 50",
    "indiavix": "NSE_INDEX|India VIX",
}

# The three F&O underlyings we analyse. The option-chain endpoint takes the
# underlying INDEX instrument key (same keys as INDEX_KEYS above).
FNO_UNDERLYINGS = {
    "nifty50": "NSE_INDEX|Nifty 50",
    "banknifty": "NSE_INDEX|Nifty Bank",
    "sensex": "BSE_INDEX|SENSEX",
}


def _num(v):
    """Coerce to float, or None. Upstox sometimes sends 0/None/absent."""
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _quote_change(v: dict) -> tuple[float | None, float | None, float | None]:
    """(last_price, previous_close, change_pct) from one Upstox quote record.

    `ohlc.close` is ambiguous: during the session it is the PREVIOUS day's
    close, but once the session settles it becomes TODAY's close — identical to
    last_price. Both quote endpoints used to handle that second case by falling
    back to `(last - open) / open`, which is the intraday move from the opening
    print, not the day's change. That is why the terminal showed Nifty +14.11
    (23985.35 vs its 23971.25 open) on a day it actually closed 10.60 points
    DOWN against the prior close.

    `net_change` is Upstox's own day change in points and is unambiguous in
    both states, so derive the previous close from it and only fall back to
    ohlc.close while it still demonstrably differs from last_price.
    """
    ohlc = v.get("ohlc") or {}
    last = _num(v.get("last_price"))
    if last is None:
        last = _num(ohlc.get("close"))
    net = _num(v.get("net_change"))

    if last is not None and net is not None:
        prev = last - net
        return last, prev, ((net / prev * 100) if prev else None)

    prev = _num(ohlc.get("close"))
    if last is not None and prev and last != prev:
        return last, prev, (last - prev) / prev * 100
    # No trustworthy previous close — report no change rather than a number
    # measured against the wrong baseline.
    return last, prev, None


def _greek(v) -> float | None:
    """
    A greek Upstox printed as literally 0.0 is a thin-quote artifact, not a
    measurement — SENSEX's nearest expiry returns iv 0.0 / delta 0.0 on live
    ATM legs that carry real OI and volume. Report it as ABSENT so nothing
    downstream renders a zero as if the leg had been priced.
    """
    return _num(v) or None


def _parse_option_chain(raw: list[dict]) -> dict:
    """
    Normalise Upstox's /v2/option/chain response into a compact shape.

    Pure function (no I/O) so the parsing is unit-testable offline.

    Input: the `data` list, each row a strike with call_options / put_options.
    Output:
        {
          "spot": float | None,
          "strikes": [
             {"strike": float,
              "call": {"ltp","oi","prev_oi","prev_close","oi_change",
                       "price_chg","iv","volume","delta"},
              "put":  {...same...}},
             ...  # sorted ascending by strike
          ],
        }
    """
    spot = None
    strikes = []
    for row in raw or []:
        if spot is None:
            spot = _num(row.get("underlying_spot_price"))
        strike = _num(row.get("strike_price"))
        if strike is None:
            continue

        def _leg(side: dict) -> dict:
            md = (side or {}).get("market_data", {}) or {}
            gk = (side or {}).get("option_greeks", {}) or {}
            oi = _num(md.get("oi"))
            prev_oi = _num(md.get("prev_oi"))
            ltp = _num(md.get("ltp"))
            # Upstox pairs `close_price` with `prev_oi` — both are the PRIOR
            # session's settled value for this leg. That is what makes an OI
            # build-up quadrant classifiable per leg (price change × OI change)
            # instead of proxied from the index move.
            prev_close = _num(md.get("close_price"))
            return {
                "ltp": ltp,
                "oi": oi,
                "prev_oi": prev_oi,
                "prev_close": prev_close,
                "oi_change": (oi - prev_oi) if (oi is not None and prev_oi is not None) else None,
                "price_chg": (ltp - prev_close) if (ltp is not None and prev_close is not None) else None,
                "iv": _greek(gk.get("iv")),
                "volume": _num(md.get("volume")),
                "delta": _greek(gk.get("delta")),
            }

        strikes.append({
            "strike": strike,
            "call": _leg(row.get("call_options", {})),
            "put": _leg(row.get("put_options", {})),
        })

    strikes.sort(key=lambda s: s["strike"])
    return {"spot": spot, "strikes": strikes}


def _equity_key(symbol: str, exchange: str = "NSE_EQ") -> str:
    """Build an Upstox instrument key for an equity symbol.

    Upstox addresses equities by ISIN, not ticker — its own holdings payload
    returns `NSE_EQ|INE364U01010`. Building `NSE_EQ|ADANIGREEN` produced a 200
    with an empty `data` map, so every equity quote call failed silently and
    looked like "Upstox has no data outside market hours". Falls back to the
    ticker form when the ISIN is unknown, which is still no worse than before.
    """
    sym = symbol.upper().replace(" ", "")
    isin = _isin_for(sym)
    return f"{exchange}|{isin or sym}"


_isin_cache: dict[str, str] | None = None


def _isin_for(symbol: str) -> str | None:
    global _isin_cache
    if _isin_cache is None:
        try:
            from db import get_connection
            with get_connection() as conn:
                _isin_cache = {
                    r["symbol"]: r["isin"] for r in conn.execute(
                        "SELECT symbol, isin FROM symbol_master WHERE isin IS NOT NULL AND isin != ''")
                }
        except Exception:
            _isin_cache = {}
    return _isin_cache.get(symbol)


def _normalize_key(raw: str) -> str:
    """Upstox echoes keys with a colon — normalize to a friendly symbol."""
    if not raw:
        return ""
    return raw.split("|")[-1].replace(":", "|").split("|")[-1]


class UpstoxClient:
    """
    Upstox API client.

    Two token tiers:
      • Analytics token (1-yr validity) → market data: quotes, candles, OHLC.
      • Access token   (daily, ~03:30 IST) → portfolio: holdings, positions.
    """

    BASE_URL = "https://api.upstox.com/v2"

    def __init__(self):
        self.analytics_token = config.upstox.analytics_token
        self.client_id = config.upstox.client_id
        self.client_secret = config.upstox.client_secret
        self.access_token = config.upstox.access_token

    # -- auth -------------------------------------------------------
    def _get_headers(self, token_type: str = "analytics") -> dict:
        token = self.analytics_token if token_type == "analytics" else self.access_token
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

    # -- market data ------------------------------------------------
    async def get_quote(self, symbols: list[str], exchange: str = "NSE_EQ") -> dict:
        """
        Live quotes for equities.

        Args:
            symbols: plain symbols, e.g. ["RELIANCE", "TCS"]
            exchange: "NSE_EQ" or "BSE_EQ"

        Returns:
            {symbol: {last_price, open, high, low, close, change_pct, volume}}
            Note: Upstox returns empty `data` for equities outside market hours.
        """
        if not self.analytics_token:
            return {"error": "Analytics token not configured"}

        keys = [_equity_key(s, exchange) for s in symbols]
        url = f"{self.BASE_URL}/market-quote/quotes"
        out: dict[str, dict] = {}

        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    url,
                    headers=self._get_headers(),
                    params={"symbol": ",".join(keys)},
                    timeout=10.0,
                )
                if r.status_code != 200:
                    return {"error": f"HTTP {r.status_code}", "status_code": r.status_code}
                data = r.json().get("data", {}) or {}
        except Exception as e:
            return {"error": str(e)}

        for raw_key, v in data.items():
            sym = _normalize_key(raw_key)
            ohlc = v.get("ohlc", {}) or {}
            last, prev_close, change_pct = _quote_change(v)
            out[sym] = {
                "last_price": last,
                "open": ohlc.get("open"),
                "high": ohlc.get("high"),
                "low": ohlc.get("low"),
                "close": prev_close,
                "volume": v.get("volume"),
                "change_pct": change_pct,
            }

        return out

    async def get_quote_by_keys(self, instrument_keys: list[str]) -> dict:
        """
        Live quotes given full instrument keys (e.g. "NSE_EQ|INE171A01029").

        Equities on Upstox are keyed by ISIN, not symbol — callers resolve the
        key via services.instruments. Returns {symbol: {last_price, change_pct, ...}}.
        """
        if not self.analytics_token or not instrument_keys:
            return {}
        url = f"{self.BASE_URL}/market-quote/quotes"
        out: dict[str, dict] = {}
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    url,
                    headers=self._get_headers(),
                    params={"symbol": ",".join(instrument_keys)},
                    timeout=10.0,
                )
                if r.status_code != 200:
                    return {}
                data = r.json().get("data", {}) or {}
        except Exception:
            return {}

        for raw_key, v in data.items():
            sym = _normalize_key(raw_key)
            ohlc = v.get("ohlc", {}) or {}
            last, prev_close, change_pct = _quote_change(v)
            out[sym] = {
                "last_price": last, "open": ohlc.get("open"), "high": ohlc.get("high"),
                "low": ohlc.get("low"), "close": prev_close,
                "volume": v.get("volume"), "change_pct": change_pct,
            }
        return out

    async def get_index_quotes(self, indices: list[str] | None = None) -> dict:
        """
        Live index quotes (works outside market hours — indices persist).

        Args:
            indices: keys into INDEX_KEYS, e.g. ["nifty50", "banknifty"].
                     Defaults to all known indices.

        Returns:
            {friendly_name: {value, change, ohlc, timestamp}}
        """
        if not self.analytics_token:
            return {"error": "Analytics token not configured"}

        wanted = indices or list(INDEX_KEYS.keys())
        keys = [INDEX_KEYS[k] for k in wanted if k in INDEX_KEYS]
        friendly = {v: k for k, v in INDEX_KEYS.items()}

        url = f"{self.BASE_URL}/market-quote/quotes"
        out: dict[str, dict] = {}

        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    url,
                    headers=self._get_headers(),
                    params={"symbol": ",".join(keys)},
                    timeout=10.0,
                )
                if r.status_code != 200:
                    return {"error": f"HTTP {r.status_code}"}
                data = r.json().get("data", {}) or {}
        except Exception as e:
            return {"error": str(e)}

        for raw_key, v in data.items():
            name = friendly.get(raw_key.replace(":", "|")) or _normalize_key(raw_key)
            ohlc = v.get("ohlc", {}) or {}
            last, _prev, change = _quote_change(v)
            out[name] = {
                "value": last,
                "change": change,
                "ohlc": ohlc,
                "timestamp": v.get("timestamp"),
            }

        return out

    async def get_candles(
        self,
        instrument_key: str,
        interval: str = "day",
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[list]:
        """
        Historical candles via the v2 historical-candle endpoint.

        The route is path-based, not query-based:
            /historical-candle/{instrument_key}/{interval}/{to_date}/{from_date}

        Args:
            instrument_key: e.g. "NSE_EQ|RELIANCE" (pipe is URL-encoded for us)
            interval: one of {1minute, 30minute, day, week, month}
            from_date / to_date: "YYYY-MM-DD". to_date defaults to today.

        Returns:
            Raw candle rows: [[timestamp, open, high, low, close, volume, oi], ...]
            Empty list on any failure (caller falls back to Yahoo).
        """
        if not self.analytics_token:
            return []

        to_d = to_date or datetime.now().strftime("%Y-%m-%d")
        path = f"{self.BASE_URL}/historical-candle/{quote(instrument_key, safe='')}/{interval}/{to_d}"
        if from_date:
            path += f"/{from_date}"

        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(path, headers=self._get_headers(), timeout=30.0)
                r.raise_for_status()
                return r.json().get("data", {}).get("candles", []) or []
        except Exception:
            return []

    async def get_intraday_candles(
        self, instrument_key: str, interval: str = "1minute"
    ) -> list[list]:
        """
        TODAY's live intraday candles (the current session's forming bars) — the
        historical endpoint above doesn't return the live day. Route:
            /historical-candle/intraday/{instrument_key}/{interval}
        interval: 1minute | 30minute. Same row shape as get_candles; [] on failure.
        """
        if not self.analytics_token:
            return []
        path = f"{self.BASE_URL}/historical-candle/intraday/{quote(instrument_key, safe='')}/{interval}"
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(path, headers=self._get_headers(), timeout=30.0)
                r.raise_for_status()
                return r.json().get("data", {}).get("candles", []) or []
        except Exception:
            return []

    # -- F&O / options ----------------------------------------------
    async def get_option_expiries(self, instrument_key: str) -> list[str]:
        """
        Available option expiry dates ("YYYY-MM-DD") for an underlying,
        nearest first. Empty list on failure.
        """
        if not self.analytics_token:
            return []
        url = f"{self.BASE_URL}/option/contract"
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    url,
                    headers=self._get_headers(),
                    params={"instrument_key": instrument_key},
                    timeout=15.0,
                )
                if r.status_code != 200:
                    return []
                data = r.json().get("data", []) or []
        except Exception:
            return []
        expiries = sorted({d.get("expiry") for d in data if d.get("expiry")})
        return expiries

    async def get_option_chain(self, instrument_key: str, expiry_date: str) -> dict:
        """
        Full option chain for an underlying at a given expiry.

        Args:
            instrument_key: underlying INDEX key, e.g. "NSE_INDEX|Nifty 50"
            expiry_date: "YYYY-MM-DD" (from get_option_expiries)

        Returns the normalised shape from _parse_option_chain, plus
        {"expiry", "instrument_key"}; or {"error": ...} on failure.
        """
        if not self.analytics_token:
            return {"error": "Analytics token not configured"}
        url = f"{self.BASE_URL}/option/chain"
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    url,
                    headers=self._get_headers(),
                    params={"instrument_key": instrument_key, "expiry_date": expiry_date},
                    timeout=20.0,
                )
                if r.status_code != 200:
                    return {"error": f"HTTP {r.status_code}: {r.text[:200]}"}
                data = r.json().get("data", []) or []
        except Exception as e:
            return {"error": str(e)}
        parsed = _parse_option_chain(data)
        parsed["expiry"] = expiry_date
        parsed["instrument_key"] = instrument_key
        return parsed

    # -- portfolio --------------------------------------------------
    async def get_portfolio_holdings(self) -> dict:
        """
        Live holdings via the daily access token.

        Returns a structured result:
          {"status": "ok", "data": [...]}
          {"status": "expired", "message": "..."}  # 401 — token expired
          {"status": "missing", "message": "..."}  # no token configured
          {"status": "error",  "message": "..."}
        """
        if not self.access_token:
            return {"status": "missing", "message": "UPSTOX_ACCESS_TOKEN not set"}

        # Upstox v2 holdings endpoint is /portfolio/long-term-holdings
        # (plain /portfolio/holdings does not exist).
        url = f"{self.BASE_URL}/portfolio/long-term-holdings"
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    url,
                    headers=self._get_headers(token_type="standard"),
                    timeout=15.0,
                )
            if r.status_code == 401:
                return {
                    "status": "expired",
                    "message": "Access token expired (regenerate via Upstox OAuth ~03:30 IST).",
                }
            if r.status_code != 200:
                return {"status": "error", "message": f"HTTP {r.status_code}: {r.text[:200]}"}
            payload = r.json()
            return {"status": "ok", "data": payload.get("data", []) or []}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # -- market meta ------------------------------------------------
    async def get_market_holidays(self) -> list[dict]:
        """
        Official NSE/BSE trading holidays (analytics token, no auth expiry).

        Returns a list of {date, description, closed_exchanges} sorted by date,
        or [] on any failure. This is the authoritative India holiday source.
        """
        if not self.analytics_token:
            return []
        url = f"{self.BASE_URL}/market/holidays"
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(url, headers=self._get_headers(), timeout=15.0)
                if r.status_code != 200:
                    return []
                data = r.json().get("data", []) or []
        except Exception:
            return []

        out = []
        for h in data:
            out.append({
                "date": h.get("date"),
                "description": h.get("description", "Trading holiday"),
                "closed_exchanges": h.get("closed_exchanges", []),
            })
        return sorted(out, key=lambda x: x.get("date") or "")

    async def get_positions(self) -> dict:
        """Live intraday positions (access token)."""
        if not self.access_token:
            return {"status": "missing", "message": "UPSTOX_ACCESS_TOKEN not set"}
        url = f"{self.BASE_URL}/portfolio/short-term-positions"
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    url,
                    headers=self._get_headers(token_type="standard"),
                    timeout=15.0,
                )
            if r.status_code == 401:
                return {"status": "expired", "message": "Access token expired."}
            if r.status_code != 200:
                return {"status": "error", "message": f"HTTP {r.status_code}"}
            return {"status": "ok", "data": r.json().get("data", []) or []}
        except Exception as e:
            return {"status": "error", "message": str(e)}


async def get_quote_with_fallback(instrument_key: str, max_staleness_seconds: float = 5.0) -> dict:
    """
    Live quote for one instrument: prefer the WebSocket tick cache
    (services.upstox_stream) when fresh, fall back to REST otherwise.

    On the REST fallback path only, cross-checks Upstox against Yahoo Finance
    via engines.verification.VerificationMembrane (its first live caller) and
    tags the result with "verified_status" (VERIFIED/SINGLE_SOURCE/CONFLICT/
    None). Existing callers of get_quote()/get_quote_by_keys() are unaffected
    — this is an additive, optional-key path, not a breaking change.
    """
    import time
    from services.upstox_stream import get_stream_manager

    tick = get_stream_manager().get_cached_tick(instrument_key)
    if tick and tick.get("ltp") is not None and (time.time() - tick["received_at"]) < max_staleness_seconds:
        return {"last_price": tick["ltp"], "close": tick.get("close"),
                "source": "stream", "verified_status": None}

    quote = await UpstoxClient().get_quote_by_keys([instrument_key])
    upstox_val = next((v for v in quote.values() if v.get("last_price")), None)
    if not upstox_val:
        return {"last_price": None, "source": "rest", "verified_status": None}

    consensus_price = upstox_val.get("last_price")
    verified_status = None

    # Yahoo only has an equivalent quote shape for equities (.NS/.BO), not
    # index instrument keys — skip verification for indices rather than
    # forcing a comparison that isn't meaningful.
    if instrument_key.startswith(("NSE_EQ|", "BSE_EQ|")):
        try:
            import asyncio
            from services.yahoo import YahooFinance
            from engines.verification import VerificationMembrane

            symbol = _normalize_key(instrument_key)
            yahoo_quote = await asyncio.to_thread(YahooFinance().get_quote, symbol)
            yahoo_price = (yahoo_quote or {}).get("current_price")
            field = VerificationMembrane().verify_price(
                upstox_price=upstox_val.get("last_price"), yahoo_price=yahoo_price, symbol=symbol,
            )
            verified_status = field.status.value
            if field.consensus_value is not None:
                consensus_price = field.consensus_value
        except Exception:
            pass

    return {**upstox_val, "last_price": consensus_price, "source": "rest",
            "verified_status": verified_status}
