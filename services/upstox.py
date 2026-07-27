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
    "niftymidcap": "NSE_INDEX|Nifty Midcap 150",
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
              "call": {"ltp","oi","prev_oi","oi_change","iv","volume","delta"},
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
            return {
                "ltp": _num(md.get("ltp")),
                "oi": oi,
                "prev_oi": prev_oi,
                "oi_change": (oi - prev_oi) if (oi is not None and prev_oi is not None) else None,
                "iv": _num(gk.get("iv")),
                "volume": _num(md.get("volume")),
                "delta": _num(gk.get("delta")),
            }

        strikes.append({
            "strike": strike,
            "call": _leg(row.get("call_options", {})),
            "put": _leg(row.get("put_options", {})),
        })

    strikes.sort(key=lambda s: s["strike"])
    return {"spot": spot, "strikes": strikes}


def _equity_key(symbol: str, exchange: str = "NSE_EQ") -> str:
    """Build an Upstox instrument key for an equity symbol."""
    sym = symbol.upper().replace(" ", "")
    return f"{exchange}|{sym}"


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
            last = v.get("last_price") or ohlc.get("close")
            prev_close = ohlc.get("close")
            open_ = ohlc.get("open")
            change_pct = None
            if last is not None and prev_close and prev_close != 0:
                if last != prev_close:
                    change_pct = (last - prev_close) / prev_close * 100
                elif open_ and open_ != 0:
                    change_pct = (last - open_) / open_ * 100
            out[sym] = {
                "last_price": last,
                "open": open_,
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
            last = v.get("last_price") or ohlc.get("close")
            prev_close = ohlc.get("close")
            open_ = ohlc.get("open")
            change_pct = None
            if last is not None and prev_close and prev_close != 0:
                if last != prev_close:
                    change_pct = (last - prev_close) / prev_close * 100
                elif open_ and open_ != 0:
                    change_pct = (last - open_) / open_ * 100
            out[sym] = {
                "last_price": last, "open": open_, "high": ohlc.get("high"),
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
            last = v.get("last_price") or ohlc.get("close")
            prev_close = ohlc.get("close")
            open_ = ohlc.get("open")
            change = None
            if last is not None and prev_close and prev_close != 0:
                if last != prev_close:
                    change = (last - prev_close) / prev_close * 100
                elif open_ and open_ != 0:
                    change = (last - open_) / open_ * 100
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
