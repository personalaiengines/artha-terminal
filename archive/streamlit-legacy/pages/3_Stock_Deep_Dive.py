"""
ARTHA Terminal - Stock Deep-Dive Page
Full-screen analysis with agent tool-use streaming and verified data panels.

Panels:
1. Identity (verified price with provenance)
2. Price 5Y (candles + DMAs)
3. Key Metrics grid
4. Peers comparison
5. Ownership (8Q)
6. Red Flags
7. SWOT (agent)
8. Sector Radar (agent)
9. Verdict (score gauge + sub-bars)
10. Agent Console side-rail
"""

import streamlit as st
import pandas as pd
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import config
from db import get_connection
from ui.theme import GLOBAL_CSS, SEBI_DISCLAIMER, metric_card, status_badge, PALETTE
from ui.utils import (
    format_number,
    section_header,
    format_change,
    render_change_toggle,
)
from ui.components import (
    candlestick_chart,
    returns_bar_chart,
    ownership_stacked_area,
    peers_comparison_bar,
    score_gauge,
    subscore_bars,
)
from engines import RedFlagEngine, ScorecardEngine, Severity
from services.stock_data import get_live_stock_data, get_sector_peers
from services.stock_analysis_llm import get_llm_analysis
from services import instruments

st.set_page_config(
    page_title="Stock Deep-Dive | ARTHA Terminal",
    page_icon=":material/query_stats:",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(GLOBAL_CSS, unsafe_allow_html=True)
render_change_toggle()  # global %/absolute change toggle (sidebar)

# ============================================
# State
# ============================================

if "deep_dive_symbol" not in st.session_state:
    st.session_state.deep_dive_symbol = None
if "llm_analysis" not in st.session_state:
    st.session_state.llm_analysis = None


# ============================================
# Helper functions — defined before use
# ============================================

@st.cache_data(ttl=1800, show_spinner=False)
def _load_symbol_data(symbol: str) -> dict | None:
    """
    Live snapshot for ANY NSE symbol via yfinance (+ Upstox live quote), shaped
    like the old DB loader. Falls back to the local DB only if the live fetch
    fails. Cached 30 min; raises nothing (returns None on total failure).
    """
    live = None
    try:
        live = get_live_stock_data(symbol)
    except Exception:
        live = None
    if live:
        return live
    return _load_from_db(symbol)


def _load_from_db(symbol: str) -> dict | None:
    """Fallback: load whatever the local DB has for a symbol."""
    data = {"symbol": symbol, "history": None, "holders": None, "live_quote": None}
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM fundamentals WHERE symbol = ?", (symbol,))
            row = cursor.fetchone()
            data["fundamentals"] = dict(row) if row else {}
            cursor.execute("SELECT * FROM computed_metrics WHERE symbol = ?", (symbol,))
            row = cursor.fetchone()
            data["metrics"] = dict(row) if row else {}
            cursor.execute(
                "SELECT * FROM shareholding WHERE symbol = ? ORDER BY quarter DESC LIMIT 8",
                (symbol,),
            )
            data["shareholding"] = [dict(r) for r in cursor.fetchall()]
            cursor.execute("SELECT * FROM symbol_master WHERE symbol = ?", (symbol,))
            row = cursor.fetchone()
            data["master"] = dict(row) if row else {}
            cursor.execute(
                "SELECT close, date FROM prices_daily WHERE symbol = ? "
                "ORDER BY date DESC LIMIT 1",
                (symbol,),
            )
            lp = cursor.fetchone()
            data["latest_close"] = lp["close"] if lp else None
            data["latest_date"] = lp["date"] if lp else None
    except Exception as e:
        st.error(f"Failed to load data: {e}")
        return None
    if data["master"] or data["fundamentals"] or data["metrics"]:
        return data
    return None


def _render_identity_panel(symbol: str, data: dict):
    master = data.get("master", {})
    company_name = master.get("company_name", symbol)
    sector = master.get("sector", "—")
    exchange = master.get("exchange", "NSE")
    cols = st.columns([2, 1, 1])
    with cols[0]:
        st.markdown(f"### {company_name}")
        st.markdown(f"<span style='color:{PALETTE['haze']};'>{symbol} · {exchange} · {sector}</span>", unsafe_allow_html=True)
    with cols[1]:
        # Price provenance: LIVE if Upstox returns a fresh last_price, else last close
        live = data.get("live_quote")
        if live and live.get("last_price"):
            price = live["last_price"]
            chg = live.get("change_pct")
            badge = status_badge("VERIFIED") + " 🟢LIVE"
            delta_str = format_change(chg, price=price) if chg is not None else ""
            delta_type = "up" if (chg or 0) >= 0 else "down"
        elif data.get("latest_close"):
            price = data["latest_close"]
            src = "yfinance" if data.get("source") == "yfinance-live" else "DB"
            delta_str = f"close {data.get('latest_date', '')}"
            delta_type = "neutral"
            badge = status_badge("SINGLE_SOURCE") + f" {src}"
        else:
            price = "—"
            delta_str = "No price data"
            delta_type = "neutral"
            badge = status_badge("CONFLICT") if False else "❓ NA"
        st.markdown(f"<div style='text-align:center;'><div class='metric-label'>Price Status</div><br>{badge}</div>", unsafe_allow_html=True)
    with cols[2]:
        st.markdown(metric_card("Latest Price",
                                 f"₹{format_number(price)}",
                                 delta_str, delta_type), unsafe_allow_html=True)


def _render_price_panel(symbol: str, data: dict):
    df = data.get("history")
    try:
        if df is None or (hasattr(df, "empty") and df.empty):
            # DB fallback path
            with get_connection() as conn:
                df = pd.read_sql_query(
                    "SELECT date, open, high, low, close, volume FROM prices_daily "
                    "WHERE symbol = ? ORDER BY date",
                    conn, params=(symbol,),
                )
        if df is not None and not df.empty:
            fig = candlestick_chart(df, title=f"{symbol} Price History", height=450)
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("No price history available for this symbol.")
    except Exception as e:
        st.warning(f"Price data unavailable: {e}")


def _render_returns_panel(data: dict):
    metrics = data.get("metrics", {})
    returns = {k: metrics.get(k) for k in ("return_1d", "return_1w", "return_1m", "return_3m", "return_6m", "return_1y", "return_3y", "return_5y")}
    if any(v is not None for v in returns.values()):
        fig = returns_bar_chart(returns, height=300)
        st.plotly_chart(fig, width="stretch")
    else:
        st.info("Returns not computed yet. Run the metrics calculator.")


def _render_metrics_panel(data: dict):
    fund = data.get("fundamentals", {})
    metrics = data.get("metrics", {})
    cols = st.columns(4)
    cells = [
        ("P/E Ratio", format_number(fund.get("pe_ratio"))),
        ("P/B Ratio", format_number(fund.get("pb_ratio"))),
        ("ROE", (format_number(fund.get("roe"), 2) + "%") if fund.get("roe") else "—"),
        ("D/E Ratio", format_number(fund.get("debt_to_equity"))),
        ("50 DMA", format_number(metrics.get("dma_50"))),
        ("200 DMA", format_number(metrics.get("dma_200"))),
        ("RSI (14)", format_number(metrics.get("rsi_14"))),
        ("Div Yield", (format_number(fund.get("dividend_yield"), 2) + "%") if fund.get("dividend_yield") else "—"),
    ]
    for i, (label, value) in enumerate(cells):
        with cols[i % 4]:
            st.markdown(metric_card(label, value), unsafe_allow_html=True)


@st.cache_data(ttl=1800, show_spinner=False)
def _peers_df(symbol: str, sector: str | None):
    """Cached sector-peer 6M returns."""
    return get_sector_peers(symbol, sector, metric="return_6m")


def _render_peers_panel(symbol: str, data: dict):
    sector = (data.get("metrics") or {}).get("sector") or (data.get("master") or {}).get("sector")
    with st.spinner("Comparing against sector peers…"):
        try:
            peers = _peers_df(symbol, sector)
        except Exception:
            peers = None
    if peers is not None and not peers.empty and len(peers) >= 2:
        fig = peers_comparison_bar(
            peers, metric="return_6m", metric_label="6M Return (%)",
            highlight=symbol.upper(),
            title=f"{symbol.upper()} vs {sector or 'sector'} peers · 6-month return",
            height=380,
        )
        st.plotly_chart(fig, width="stretch")
        st.caption("Peers from the curated NIFTY-50 sector map · 6M returns computed live (yfinance).")
    else:
        st.info(f"Not enough same-sector peers to compare (sector: {sector or 'unknown'}).")


def _render_ownership_panel(symbol: str, data: dict):
    own = data.get("ownership")
    if own and (own.get("promoter") or own.get("institutions")):
        promoter, insts, public = own["promoter"], own["institutions"], own["public"]
        cols = st.columns(3)
        cols[0].markdown(metric_card("Promoter / Insider", f"{promoter:.1f}%"), unsafe_allow_html=True)
        cols[1].markdown(metric_card("Institutions (FII+DII)", f"{insts:.1f}%"), unsafe_allow_html=True)
        cols[2].markdown(metric_card("Public / Other", f"{public:.1f}%"), unsafe_allow_html=True)
        # a simple horizontal composition bar
        bar = (
            f"<div style='display:flex; height:22px; border-radius:6px; overflow:hidden; "
            f"margin:0.75rem 0; font-size:0.7rem; font-weight:600; color:{PALETTE['abyss']};'>"
            f"<div style='width:{promoter}%; background:{PALETTE['surge']}; text-align:center;'>{promoter:.0f}%</div>"
            f"<div style='width:{insts}%; background:{PALETTE['volt']}; text-align:center;'>{insts:.0f}%</div>"
            f"<div style='width:{public}%; background:{PALETTE['haze']}; text-align:center;'>{public:.0f}%</div>"
            f"</div>"
        )
        st.markdown(bar, unsafe_allow_html=True)
        cnt = own.get("institutions_count")
        st.caption(
            f"Ownership split via yfinance{' · ' + str(int(cnt)) + ' institutional holders' if cnt else ''}. "
            f"'Promoter/Insider' approximates promoter holding; the exact quarterly "
            f"promoter/FII/DII/public split (NSE filing) isn't in this source."
        )
    else:
        # DB fallback (tracked symbols may have quarterly filings)
        try:
            with get_connection() as conn:
                df = pd.read_sql_query(
                    "SELECT quarter, promoter_share, fitl_share, ditl_share, public_share "
                    "FROM shareholding WHERE symbol = ? ORDER BY quarter",
                    conn, params=(symbol,),
                )
            if not df.empty:
                fig = ownership_stacked_area(df, height=350)
                st.plotly_chart(fig, width="stretch")
            else:
                st.info("Ownership breakdown isn't available for this symbol from the "
                        "current data sources.")
        except Exception as e:
            st.warning(f"Ownership data unavailable: {e}")

    # institutional holders detail, when yfinance exposes it
    holders = data.get("holders")
    if holders is not None and hasattr(holders, "empty") and not holders.empty:
        with st.expander("Top institutional holders", expanded=False):
            hcols = [c for c in ("Holder", "Shares", "pctHeld", "Value", "Date Reported")
                     if c in holders.columns]
            st.dataframe(holders[hcols] if hcols else holders, width="stretch", hide_index=True)


def _render_red_flags_panel(symbol: str, data: dict):
    engine = RedFlagEngine()
    # Prefer the statement-derived engine inputs (de_ratio/ocf/pat/...); fall back
    # to raw fundamentals for DB-loaded symbols.
    rf_data = data.get("red_flag_inputs") or data.get("fundamentals", {})
    shareholding = data.get("shareholding", [])
    findings = engine.scan_flags_only(fundamentals=rf_data, shareholding=shareholding, symbol=symbol)
    summary = engine.get_summary(engine.scan(fundamentals=rf_data, shareholding=shareholding, symbol=symbol))
    overall = summary["overall_status"]

    # A friendlier headline: "INCOMPLETE" only means some checks lacked data. If
    # nothing failed or warned, say so plainly.
    clean_partial = overall == "INCOMPLETE" and summary["warn"] == 0 and summary["fail"] == 0
    label = "NO FLAGS FOUND" if clean_partial else overall
    oc = {"CRITICAL": PALETTE["flare"], "CAUTION": PALETTE["volt"], "CLEAN": PALETTE["surge"],
          "NO FLAGS FOUND": PALETTE["surge"], "INCOMPLETE": PALETTE["haze"]}
    color = oc.get(label, PALETTE["haze"])
    note = ""
    if summary["na"]:
        note = (f" · {summary['na']} check(s) skipped for lack of data "
                f"(e.g. promoter pledge/holding needs quarterly filings)")
    st.markdown(
        f"<div style='text-align:center; padding:0.75rem; border:1px solid {color}; "
        f"border-radius:8px; color:{color}; font-weight:600; margin-bottom:1rem;'>"
        f"Overall: {label} · {summary['pass']} PASS, {summary['warn']} WARN, "
        f"{summary['fail']} FAIL{note}</div>",
        unsafe_allow_html=True,
    )
    for f in findings:
        if f.severity == Severity.PASS:
            continue
        sc = {Severity.WARN: PALETTE["volt"], Severity.FAIL: PALETTE["flare"], Severity.NA: PALETTE["haze"]}
        icon = {"WARN": "⚠️", "FAIL": "🚫", "NA": "❓"}.get(f.severity.value, "•")
        with st.expander(f"{icon} {f.name} — {f.severity.value}", expanded=False):
            st.markdown(f.message)
            if f.threshold is not None:
                st.caption(f"Threshold: {f.threshold}")
            st.caption(f"Rule ID: `{f.rule_id}`")


def _compute_scorecard(symbol: str, data: dict) -> dict | None:
    try:
        engine = ScorecardEngine()
        sc = engine.compute(symbol=symbol, data=data.get("metrics", {}) or {}, fundamentals=data.get("fundamentals", {}), shareholding=data.get("shareholding", []))
        return sc.to_dict()
    except Exception as e:
        st.warning(f"Scorecard computation failed: {e}")
        return None


def _run_llm_analysis(symbol: str, data: dict):
    """Grounded senior-analyst LLM read on the live snapshot. Works for any stock."""
    snap = dict(data)
    # Attach a red-flag summary so the LLM can weigh it (grounded, not invented).
    try:
        rf = RedFlagEngine()
        summ = rf.get_summary(rf.scan(
            fundamentals=data.get("red_flag_inputs") or data.get("fundamentals", {}),
            shareholding=data.get("shareholding", []), symbol=symbol))
        snap["red_flags"] = (f"overall {summ['overall_status']}, {summ['warn']} warnings, "
                             f"{summ['fail']} failures, {summ['na']} insufficient-data")
    except Exception:
        pass
    try:
        res = get_llm_analysis(snap)
    except Exception as e:
        res = {"markdown": "", "ok": False, "model": None, "error": str(e)}
    res["symbol"] = symbol
    st.session_state.llm_analysis = res


def _render_llm_analysis(symbol: str):
    res = st.session_state.get("llm_analysis")
    if not res or res.get("symbol") != symbol:
        return
    if not res.get("ok"):
        st.warning("The analysis model is busy right now — try again in a moment. "
                   "(All the data panels above are live regardless.)")
        return
    st.markdown(res["markdown"])
    st.caption(f"🤖 Generated by NVIDIA NIM `{res.get('model','')}` · grounded strictly on the "
               f"verified figures above · educational, not investment advice.")


def _render_verdict_panel(scorecard: dict | None):
    if not scorecard:
        st.info("Scorecard requires fundamentals data. Run the fundamentals ETL.")
        return
    cols = st.columns([1, 2])
    with cols[0]:
        fig = score_gauge(scorecard["total_score"], height=350)
        st.plotly_chart(fig, width="stretch")
    with cols[1]:
        st.markdown("#### Sub-Scores")
        fig = subscore_bars(scorecard["sub_scores"], height=300)
        st.plotly_chart(fig, width="stretch")
        penalty = scorecard["red_flag_penalty"]
        raw = scorecard["raw_weighted_score"]
        final = scorecard["total_score"]
        st.markdown(
            f"<div style='color:{PALETTE['haze']}; font-family:JetBrains Mono; font-size:0.85rem; padding:0.5rem;'>"
            f"Raw weighted: <b style='color:{PALETTE['frost']}'>{raw:.2f}</b> · "
            f"Red-flag penalty: <b style='color:{PALETTE['flare']}'>-{penalty:.1f}</b> · "
            f"Final: <b style='color:{PALETTE['surge']}'>{final:.2f}</b></div>",
            unsafe_allow_html=True,
        )


@st.cache_data(ttl=3600, show_spinner=False)
def _symbol_matches(query: str) -> list[dict]:
    """Live NSE symbol suggestions from the Upstox instrument master (cached)."""
    try:
        return instruments.search(query, limit=15)
    except Exception:
        return []


def _build_search_options(query: str) -> dict:
    """
    Live dropdown options across ALL ~2,390 NSE equities (Upstox instrument
    master), matched by symbol or company name. The exact typed symbol is always
    offered too, so any valid NSE ticker can be analysed live.
    """
    q = query.strip().upper()
    options: dict[str, str] = {}
    for r in _symbol_matches(query):
        options[f"{r['symbol']} — {r['name']}"] = r["symbol"]
    if q and q.isalnum() and q not in options.values():
        options[f"{q} — (analyze live)"] = q
    return options


# ============================================
# Main render function
# ============================================

def render_page():
    """Main page render — header, search, analysis panels, and agent console."""
    st.markdown("# Stock deep-dive")
    st.markdown(
        f"<p style='color:{PALETTE['haze']};'>Search any NSE stock — live fundamentals, "
        f"price history, returns, red flags and scorecard fetched on demand.</p>",
        unsafe_allow_html=True,
    )

    search_col, go_col = st.columns([4, 1])
    with search_col:
        search_query = st.text_input(
            "Search symbol or company",
            placeholder="e.g., FEDERALBNK, RELIANCE, HDFCBANK, Tata Consultancy…",
            key="symbol_search",
        )
    with go_col:
        st.write(""); st.write("")
        analyze_btn = st.button("🔍 Analyze", type="primary", width="stretch")

    if search_query:
        options = _build_search_options(search_query)
        if options:
            selected = st.selectbox("Matching symbols", options=list(options.keys()), key="search_select")
            st.session_state.deep_dive_symbol = options[selected]
        else:
            st.info(f"No match for '{search_query}'. Type an exact NSE symbol (e.g. FEDERALBNK) to analyze it live.")

    if analyze_btn and st.session_state.deep_dive_symbol:
        st.session_state.llm_analysis = None

    if st.session_state.deep_dive_symbol:
        symbol = st.session_state.deep_dive_symbol
        with st.spinner(f"Loading live data for {symbol}…"):
            symbol_data = _load_symbol_data(symbol)
        if symbol_data:
            section_header("Identity", "🪪"); _render_identity_panel(symbol, symbol_data)
            section_header("Price Action (5Y)", "📈"); _render_price_panel(symbol, symbol_data)
            section_header("Returns Analysis", "📊"); _render_returns_panel(symbol_data)
            section_header("Key Metrics", "📋"); _render_metrics_panel(symbol_data)
            section_header("Peer Comparison", "👥"); _render_peers_panel(symbol, symbol_data)
            section_header("Ownership", "🏛️"); _render_ownership_panel(symbol, symbol_data)
            section_header("Red Flags", "🚩"); _render_red_flags_panel(symbol, symbol_data)
            section_header("AI Analysis (LLM · grounded)", "🧠")
            scorecard = _compute_scorecard(symbol, symbol_data)
            st.caption("A senior-analyst read written by an LLM from the verified numbers "
                       "above — works for any NSE stock.")
            if st.button("🚀 Generate AI Analysis", type="primary"):
                with st.spinner("Senior-analyst LLM is reviewing the numbers…"):
                    _run_llm_analysis(symbol, symbol_data)
            _render_llm_analysis(symbol)
            section_header("Verdict", "🎯"); _render_verdict_panel(scorecard)
        else:
            st.warning(f"Couldn't load live data for '{symbol}'. It may not be a valid NSE "
                       f"equity symbol, or the data source is momentarily unavailable — try again.")

    st.markdown("---")
    st.markdown(SEBI_DISCLAIMER, unsafe_allow_html=True)


render_page()