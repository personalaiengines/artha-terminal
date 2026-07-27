# ARTHA Terminal - Live Data Integration (2026-01-16)

## ✅ Summary

Converted all demo/sample data flows to **real Upstox API data** while maintaining graceful fallbacks and honest state messaging.

## 🔧 Changes Made

### 1. Upstox Client (`services/upstox.py`)
- **Fixed** instrument-key format: `NSE_EQ\|RELIANCE`, `NSE_INDEX\|Nifty 50`
- **Added** `get_quote()` for live equity quotes (returns data during market hours)
- **Added** `get_index_quotes()` for 24/7 index values (Nifty 50, Bank Nifty, Sensex, Midcap)
- **Fixed** `get_portfolio_holdings()` with proper status handling (`ok`/`expired`/`missing`)

### 2. Portfolio Page (`pages/2_My_Portfolio.py`)
- **REMOVED** hardcoded 6-stock demo fallback
- **ADDED** real Upstox holdings API call
- **ADDED** explicit state messaging:
  - ✅ Connected, empty portfolio
  - 🔐 Token expired (401)
  - ⚠️ Token missing (no credentials)
  - ⚖️ Review / Log In button present in token expiry
- **OPTIONAL** sample data preview, **clearly labeled everywhere**

### 3. Live Indices (`ui/utils.py`)
- **CHANGED** `get_indices_data()` to fetch from Upstox (60s TTL cache)
- **ADDED** live status badge: 🟢 LIVE / ⚪ offline
- **Fallback** to DB clos

e only when API is down

### 4. Stock Deep-Dive (`pages/3_Stock_Deep_Dive.py`)
- **ADDED** latest close from `prices_daily` DB table
- **ADDED** best-effort Upstox enrichment for live quotes
- **EXPECTED** provenance badge: 🟢 LIVE / DB / N/A

### 5. Hero "Initializing..." Fix (`ui/components/threejs/bull_bear_hero.py`)
- **ADDED** 6s timeout failsafe (prevents stuck "Initializing...")
- **DEGRADES** to "Live market data 📈" (Three.js blocked by sandbox/CDN)

### 6. Landing Page Hero (`main.py`)
- **ADDED** live index values from Upstox (Nifty 50, Bank Nifty)
- **ADDED** status badge: 🟢 LIVE vs ⚪ offline

### 7. Quick Stats (`main.py`)
- **ADDED** live index + DB symbol count

### 8. Code Cleanup
- `services/yahoo.py` and `services/search.py` are the canonical modules
  (`services/__init__.py` imports from them). The duplicate `YahooFinance` /
  `SearchService` copies that had been added to `upstox.py` were dead code and
  are now removed.
- Removed sync of `tests/` in `Dockerfile` (light container, retained)

---

## 📊 Current DB State (verified 2026-07-16)

**There are two separate databases — do not confuse them:**

| | local `db/artha.db` | container volume `artha-db` (`/data/db/artha.db`) |
|---|---|---|
| Used by | `streamlit run main.py` on the host | the Docker app (`ARTHA_DB_PATH=/data/db/artha.db`) |
| symbol_master | 20 | 20 |
| prices_daily | 4,940 | **4,937 (4,920 Upstox / 17 Yahoo)** |
| fundamentals | 20 | 20 |
| computed_metrics | 20 | 20 |
| shareholding | 0 (ETL needed) | 0 |

The 17 remaining Yahoo rows are dated 2025-07-16 — one day older than the
365-day Upstox fetch window, so nothing re-sources them. They are real data,
not phantoms; leave them or widen `days=` to re-fetch.

`.dockerignore` excludes `*.db`, and the named volume shadows `/app/db` anyway,
so **host ingestion never reaches the container**. After rebuilding, re-run
`docker compose exec artha python scripts/ingest_all.py` to refresh the volume.

---

## 🚀 What Works Now

| Feature | Status |
|---------|--------|
| Navigation (pages load) | ✅ Fixed |
| Home / Hero (live indices) | ✅ Live data |
| Market Analysis page | ✅ Live Nifty/Bank Nifty |
| Stock Deep-Dive | ✅ Real DB prices, Upstox enrichment |
| Portfolio Holdings | ✅ Real Upstox API (if token valid) |
| Error states | ✅ Honest (expired token, empty portfolio) |

---

## ⚠️ Known Constraints

1. **Portfolio Holdings** requires a **daily access token** (regenerates ~03:30 IST via Upstox OAuth). Your current token is expired (401 from API).
   - To fix: Visit Upstox Developer Console → regenerate OAuth token → update UPSTOX_ACCESS_TOKEN in `.env`

2. **Equity Live Quotes** are **empty outside market hours** (9:15 AM - 3:30 PM IST). ARTHA falls back cleanly to most recent DB close.

3. **Symbol Counts**: 20 stocks ingested, from a hardcoded seed list in
   `ingestion/symbol_etl.py`. To re-ingest, run `python scripts/ingest_all.py`
   (`python -m ingestion.symbol_etl` does nothing — the module has no
   `__main__` block).

4. **Shareholding**: 0 rows (ETL pipeline disabled; fundamentals etl populates quarterly holdings)

5. **Upstox instrument keys are ISIN-based** (`NSE_EQ|INE002A01018`), not
   symbol-based — a key built from the ticker is rejected with UDAPI100011.
   `PriceETL._to_instrument_key` resolves the ISIN from `symbol_master`, so
   **symbols ingested without an ISIN silently fall back to Yahoo**. Seed ISINs
   go stale after splits/demergers; verify against
   `https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz`.

---

## 🔄 Next Steps (Optional)

- [ ] Set up SearxNG container for unlimited search fallback
- [ ] Run `ingestion.fundamentals_etl` to populate quarterly shareholding
- [ ] Rebuild port → generation access token via Upstox OAuth flow
- [ ] Run `ingestion.symbol_etl` to populate >500 symbols
- [ ] Wire Agent orchestration (LLM client + tools) for SWOT/Verdict

---

**All core data flows now use live APIs.** No more hidden demo data! All sample/fallback paths are explicitly labeled and user-opt-in.