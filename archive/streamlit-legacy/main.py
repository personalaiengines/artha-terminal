"""
ARTHA Terminal - Main Entry Point
Run with: streamlit run main.py

Landing page with Bull-vs-Bear Three.js hero and entry cards to each route.
"""

import streamlit as st
from pathlib import Path
import sys

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from config import config
from ui.theme import GLOBAL_CSS, SEBI_DISCLAIMER
from ui.utils import get_db_status, get_symbol_master, render_change_toggle
from ui.components import (
    render_market_pulse,
    render_global_markets,
    render_market_events,
    render_index_levels,
    render_institutional_flows,
    render_token_banner,
)

# ============================================
# Page Configuration
# ============================================

st.set_page_config(
    page_title="ARTHA Terminal | Indian Equities Research",
    page_icon=":material/monitoring:",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(GLOBAL_CSS, unsafe_allow_html=True)

# ============================================
# Configuration Validation
# ============================================

if "config_warnings" not in st.session_state:
    st.session_state.config_warnings = config.validate()

db_status = get_db_status()

# ============================================
# Landing Page
# ============================================

def render_landing():
    """Render the landing page."""

    # Global %/absolute change toggle (sidebar) — drives every change display
    render_change_toggle()

    # === Market Pulse Hero (live indices + breadth + AI strategist read) ===
    render_market_pulse()

    # === Upstox token banner (only shows when regeneration is needed) ===
    render_token_banner()

    # === Institutional Flows (FII / DII) ===
    st.markdown("---")
    render_institutional_flows()

    # === Configuration & DB Status ===
    st.markdown("---")
    show_status_panel()

    # === Entry Cards ===
    st.markdown("### Navigate")
    st.caption("Jump to a workspace.")

    routes = [
        ("pages/1_Market_Analysis.py", "Market analysis", ":material/bar_chart:",
         "Indices, movers, volatility radar, live news"),
        ("pages/2_My_Portfolio.py", "My portfolio", ":material/account_balance_wallet:",
         "Holdings, allocation wheel, health score, decisions"),
        ("pages/3_Stock_Deep_Dive.py", "Stock deep-dive", ":material/query_stats:",
         "Candles, fundamentals, red flags, SWOT, verdict"),
        ("pages/4_FnO_Analysis.py", "F&O analysis", ":material/bolt:",
         "NIFTY / BANK NIFTY / SENSEX game plan, levels, OI, strategy"),
    ]
    for col, (path, label, icon, hint) in zip(st.columns(4), routes):
        with col.container(border=True):
            st.page_link(path, label=label, icon=icon, width="stretch")
            st.caption(hint)

    # === Global Markets & Commodities (live, auto-refreshing) ===
    st.markdown("---")
    render_global_markets()

    # === Market Events (one-week lookahead) ===
    st.markdown("---")
    try:
        tracked = get_symbol_master()["symbol"].tolist()
    except Exception:
        tracked = []
    render_market_events(tracked, days_ahead=7)

    # === Index Levels & Senior-Analyst View ===
    st.markdown("---")
    render_index_levels()

    # === Build Status ===
    st.markdown("---")
    _render_build_status()


def show_status_panel():
    """Show configuration warnings and DB status."""
    warnings = st.session_state.config_warnings
    has_warnings = bool(warnings)

    if has_warnings:
        with st.expander(f"Configuration status ({len(warnings)} warnings)",
                         icon=":material/settings:", expanded=False):
            for warning in warnings:
                st.warning(warning)

    # Database status
    if not db_status["db_exists"]:
        st.info(
            "Database not yet initialized. Run "
            "`python -c \"from db import init_database; init_database()\"` to set up the schema.",
            icon=":material/database:",
        )
    elif db_status["symbol_count"] == 0:
        st.info(
            "Database ready but empty. Run ingestion to populate symbols, prices, and fundamentals.",
            icon=":material/database:",
        )
    else:
        st.caption(
            f":material/check_circle: Database ready · {db_status['symbol_count']:,} symbols · "
            f"{db_status['price_count']:,} price candles"
        )


def _render_build_status():
    """Show the stack footer."""
    st.caption(
        "Streamlit · OpenRouter Claude + Nvidia NIM · SerpAPI/SearxNG · Upstox · SQLite WAL"
    )


# ============================================
# Render
# ============================================

render_landing()

# ============================================
# SEBI Disclaimer (Persistent Footer)
# ============================================

st.markdown(SEBI_DISCLAIMER, unsafe_allow_html=True)
