"""
ARTHA Terminal - Market Analysis Page
Top movers, volume leaders, live sector news, and educational strategy notes.

Note: live indices, breadth, FII/DII and index levels live on the landing page
(main.py) — this page deliberately does NOT repeat them.
"""

import streamlit as st
import pandas as pd
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ui.theme import GLOBAL_CSS, SEBI_DISCLAIMER, PALETTE
from ui.utils import section_header, format_change, render_change_toggle
from ui.components import render_news_feed, render_headline_ticker
from services.market_news import get_live_market_news
from services.movers import get_top_movers

st.set_page_config(
    page_title="Market Analysis | ARTHA Terminal",
    page_icon=":material/bar_chart:",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(GLOBAL_CSS, unsafe_allow_html=True)
render_change_toggle()  # global %/absolute change toggle (sidebar)


# ============================================
# Data loaders
# ============================================

@st.cache_data(ttl=900, show_spinner=False)
def _load_movers() -> dict:
    """Market-wide top gainers/losers (NSE → yfinance). Raises on empty to skip caching."""
    res = get_top_movers(top_n=10)
    if not res.get("ok"):
        raise RuntimeError("no movers")
    return res


def _render_mover_row(item: dict, is_gainer: bool):
    """Render a single gainer/loser with a coloured % delta and last price."""
    symbol = item["symbol"]
    ret = item["pct"]
    price = item.get("price")
    price_txt = f"₹{price:,.2f}" if price is not None else ""
    color = PALETTE["surge"] if is_gainer else PALETTE["flare"]
    arrow = "▲" if is_gainer else "▼"
    st.markdown(
        f"<div style='display:flex; justify-content:space-between; "
        f"align-items:center; padding:0.4rem 0.5rem; "
        f"border-bottom:1px solid {PALETTE['grid']};'>"
        f"<span style='color:{PALETTE['frost']}; font-weight:500;'>{symbol}</span>"
        f"<span style='display:flex; gap:0.75rem; align-items:center;'>"
        f"<span style='color:{PALETTE['haze']}; font-family:JetBrains Mono; "
        f"font-size:0.8rem;'>{price_txt}</span>"
        f"<span style='color:{color}; font-family:JetBrains Mono; "
        f"font-weight:600;'>{arrow} {format_change(ret, price=price)}</span></span>"
        f"</div>",
        unsafe_allow_html=True,
    )


@st.cache_data(ttl=1800, show_spinner=False)
def _live_news():
    """Live, LLM-curated market news. Raises on empty so failures aren't cached."""
    res = get_live_market_news(limit=8)
    if not res.get("items"):
        raise RuntimeError("no news")
    return res


# ============================================
# Main render function
# ============================================

def render_page():
    st.markdown("# Market analysis")
    st.markdown(
        f"<p style='color:{PALETTE['haze']};'>Top movers, volume leaders, and sector "
        f"news. Live indices, breadth and institutional flows are on the home page. "
        f"SEBI-safe educational framing.</p>",
        unsafe_allow_html=True,
    )

    # Top Gainers / Losers — market-wide, not just tracked symbols
    section_header("Top Gainers & Losers", "📈📉")
    hdr_col, refresh_col = st.columns([5, 1])
    with refresh_col:
        if st.button("🔄 Refresh", width="stretch", key="movers_refresh",
                     help="Recompute market movers now"):
            _load_movers.clear()
    try:
        with st.spinner("Ranking market-wide movers…"):
            movers = _load_movers()
        gainers, losers = movers["gainers"], movers["losers"]
        st.caption(f"Source: {movers['source']} · last completed session.")
    except Exception:
        movers, gainers, losers = None, [], []
        st.caption("Movers source (NSE / yfinance) is unavailable right now — try Refresh.")

    cols = st.columns(2)
    with cols[0]:
        st.markdown("#### 🟢 Top Gainers")
        if gainers:
            for item in gainers:
                _render_mover_row(item, is_gainer=True)
        else:
            st.info("Gainers unavailable — the market data source didn't respond.")

    with cols[1]:
        st.markdown("#### 🔴 Top Losers")
        if losers:
            for item in losers:
                _render_mover_row(item, is_gainer=False)
        else:
            st.info("Losers unavailable — the market data source didn't respond.")

    st.markdown("---")

    # Top Movers by Volume — market-wide, from the same broad universe
    section_header("Top Movers by Volume", "🔊")
    vol_items = (movers or {}).get("volume", []) if movers else []
    if vol_items:
        st.caption("Most-traded stocks by share volume on the last session, across "
                   "the NIFTY-100+ universe.")
        vol_df = pd.DataFrame(vol_items)
        vol_df = vol_df[["symbol", "volume", "price", "pct", "value_cr"]].rename(columns={
            "symbol": "Symbol",
            "volume": "Volume (shares)",
            "price": "Close (₹)",
            "pct": "Day Change (%)",
            "value_cr": "Value traded (₹ Cr)",
        })
        st.dataframe(
            vol_df,
            width="stretch",
            hide_index=True,
            column_config={
                "Volume (shares)": st.column_config.NumberColumn(format="%d"),
                "Day Change (%)": st.column_config.NumberColumn(format="%+.2f"),
            },
        )
    else:
        st.info("Volume leaders unavailable — the market data source didn't respond. "
                "Try the Refresh button in Top Gainers & Losers above.")

    st.markdown("---")

    # Live News — fetched live via open-source search + curated by an LLM
    section_header("Live News", "📰")
    news_col, btn_col = st.columns([5, 1])
    with btn_col:
        if st.button("🔄 Refresh", width="stretch", help="Fetch fresh headlines now"):
            _live_news.clear()
    try:
        with st.spinner("Fetching & curating live market news…"):
            news = _live_news()
    except Exception:
        news = {"items": [], "llm_used": False}

    news_items = news.get("items", [])
    if news_items:
        source_note = (
            "🤖 Curated by NVIDIA NIM LLM from live web search (SerpAPI → SearxNG)"
            if news.get("llm_used")
            else "Live web search (SerpAPI → SearxNG) · LLM curation unavailable, showing raw hits"
        )
        st.caption(source_note)
        render_headline_ticker(news_items)
        render_news_feed(news_items, title="Latest Market Headlines")
    else:
        st.info(
            "Couldn't fetch live news right now — the search provider (SerpAPI/SearxNG) "
            "returned nothing. Check SERPAPI_KEY in your .env, or try Refresh in a moment."
        )

    st.markdown("---")

    # Trading Strategies (Educational)
    section_header("Trading Strategies (Educational Concepts)", "🎓")
    with st.expander("📖 Moving Average Crossover", expanded=False):
        st.markdown("""
        **Concept:** A bullish signal occurs when a short-term moving average (e.g., 50 DMA)
        crosses above a long-term moving average (e.g., 200 DMA) — known as a "Golden Cross."
        A bearish "Death Cross" is the reverse.

        **Educational Note:** This is a trend-following concept, not a buy/sell recommendation.
        Always combine with fundamental analysis and risk management.
        """)

    with st.expander("📖 Relative Strength Index (RSI)", expanded=False):
        st.markdown("""
        **Concept:** RSI measures momentum on a 0-100 scale. Traditionally, RSI > 70 suggests
        "overbought" conditions and RSI < 30 suggests "oversold."

        **Educational Note:** RSI is a momentum oscillator, not a standalone signal.
        Overbought does not mean "sell" — strong trends can sustain high RSI for extended periods.
        """)

    with st.expander("📖 D/E Ratio and Leverage", expanded=False):
        st.markdown("""
        **Concept:** The Debt-to-Equity ratio measures financial leverage. High D/E (> 2 for
        non-BFSI sectors) can indicate elevated risk during economic downturns.

        **Educational Note:** Leverage norms vary by industry. BFSI and Real Estate typically
        operate with higher leverage by design. ARTHA's red-flag engine applies sector-aware thresholds.
        """)

    st.markdown("---")
    st.markdown(SEBI_DISCLAIMER, unsafe_allow_html=True)


render_page()
