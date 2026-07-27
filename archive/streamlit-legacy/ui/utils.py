"""
ARTHA Terminal - UI Utilities
Shared helpers for Streamlit pages: formatting, value coloring, data loading.
"""

import streamlit as st
import pandas as pd
import sys
from pathlib import Path
from typing import Optional, List

sys.path.insert(0, str(Path(__file__).parent.parent))

from ui.theme import PALETTE, section_head
from config import config
from db import get_connection


def format_number(value: Optional[float], decimals: int = 2, prefix: str = "") -> str:
    """Format a number with Indian-style grouping."""
    if value is None:
        return "—"
    try:
        formatted = f"{value:,.{decimals}f}"
        return f"{prefix}{formatted}"
    except (ValueError, TypeError):
        return "—"


def format_cr(value: Optional[float], decimals: int = 2) -> str:
    """Format market cap in crores (₹ Cr)."""
    if value is None:
        return "—"
    return f"₹{value:,.{decimals}f} Cr"


def color_for_value(value: float, inverse: bool = False) -> str:
    """Return color name based on positive/negative value."""
    if value is None:
        return "neutral"
    if inverse:
        return "up" if value < 0 else "down"
    return "up" if value > 0 else "down"


def delta_html(delta: float, suffix: str = "%") -> str:
    """Render a colored delta badge."""
    if delta is None:
        return ""
    color_class = "neon-success" if delta > 0 else (
        "neon-danger" if delta < 0 else "neon-muted"
    )
    arrow = "▲" if delta > 0 else ("▼" if delta < 0 else "▬")
    return f'<span class="{color_class}">{arrow} {delta:+.2f}{suffix}</span>'


# ------------------------------------------------------------------
# Global %/absolute change display toggle (shared across every page)
# ------------------------------------------------------------------

def change_mode() -> str:
    """Current change-display mode: 'pct' (default) or 'abs' (point/₹ move)."""
    return st.session_state.get("change_mode", "pct")


def format_change(
    change_pct: Optional[float],
    *,
    price: Optional[float] = None,
    abs_value: Optional[float] = None,
    prefix: str = "",
    decimals: int = 2,
) -> str:
    """
    Signed change string honoring the global %/absolute toggle.

    • Percent mode → "+1.23%".
    • Absolute mode → the actual move. Uses `abs_value` when the caller already
      has it (e.g. ₹ P&L), otherwise derives it from price & pct
      (abs = price·pct / (100+pct), the exact inverse of pct = (last-prev)/prev).
    Returns "—" when nothing is available. Sign is always shown; callers keep
    their own arrow/colour, which key off the sign of change_pct.
    """
    if change_mode() == "abs":
        av = abs_value
        if av is None and price is not None and change_pct is not None:
            denom = 100 + change_pct
            av = price * change_pct / denom if denom else 0.0
        if av is None:
            return "—"
        return f"{prefix}{av:+,.{decimals}f}"
    if change_pct is None:
        return "—"
    return f"{change_pct:+.2f}%"


def render_change_toggle() -> None:
    """
    Render the global %/points display toggle inline (right-aligned).

    Call once per page. Writes st.session_state['change_mode']; every change
    display reads it via format_change(), so one control drives the whole app.
    Rendered in the page body (not the sidebar, which is collapsed by default)
    so it's always visible.
    """
    _, right = st.columns([5, 1.4])
    with right:
        choice = st.segmented_control(
            "Change display",
            ["%", "₹ / pts"],
            default="%" if change_mode() == "pct" else "₹ / pts",
            key="_change_toggle",
            label_visibility="collapsed",
            help="Show price/value moves as % change or as the absolute "
                 "point/₹ change. Applies across the whole app.",
        )
    # segmented_control returns None when the user deselects — keep the last mode.
    if choice is not None:
        st.session_state["change_mode"] = "abs" if choice == "₹ / pts" else "pct"


@st.cache_data(ttl=300, show_spinner=False)
def get_symbol_master() -> pd.DataFrame:
    """Load the symbol master table (cached)."""
    try:
        with get_connection() as conn:
            return pd.read_sql_query(
                "SELECT symbol, company_name, exchange, industry, sector, cap_segment FROM symbol_master",
                conn,
            )
    except Exception:
        return pd.DataFrame(
            columns=["symbol", "company_name", "exchange", "industry", "sector", "cap_segment"]
        )


@st.cache_data(ttl=15, show_spinner=False)
def get_indices_data() -> dict:
    """
    Live index values (cached 60s).

    Fetches Nifty 50 / Bank Nifty / Sensex / Midcap from the Upstox
    analytics token. Falls back to static values only if the API is
    unreachable, so the UI never breaks.
    """
    live = _fetch_live_indices()
    if live:
        return live

    # Static fallback (clearly stale) — only used when the API is down
    return {
        "nifty50": {"value": 0, "change": 0.0, "color": "up", "live": False},
        "sensex": {"value": 0, "change": 0.0, "color": "up", "live": False},
        "banknifty": {"value": 0, "change": 0.0, "color": "down", "live": False},
        "niftymidcap": {"value": 0, "change": 0.0, "color": "up", "live": False},
    }


def _fetch_live_indices() -> dict | None:
    """Sync wrapper that calls the async Upstox index-quote endpoint."""
    import asyncio

    async def _go():
        from services import UpstoxClient
        client = UpstoxClient()
        result = await client.get_index_quotes()
        if isinstance(result, dict) and "error" in result:
            return None
        out = {}
        for name, v in result.items():
            value = v.get("value")
            if value is None:
                continue
            change = v.get("change") or 0.0
            out[name.lower().replace(" ", "")] = {
                "value": value,
                "change": change,
                "color": "up" if change >= 0 else "down",
                "live": True,
            }
        return out if out else None

    try:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_go())
        finally:
            loop.close()
    except Exception:
        return None


def search_symbols(query: str, limit: int = 10) -> List[dict]:
    """Local typeahead search over symbol_master (zero API calls)."""
    if not query or len(query) < 1:
        return []

    df = get_symbol_master()
    if df.empty:
        return []

    query_upper = query.upper()
    matches = df[
        df["symbol"].str.upper().str.contains(query_upper, na=False)
        | df["company_name"].str.upper().str.contains(query_upper, na=False)
    ]

    results = []
    for _, row in matches.head(limit).iterrows():
        results.append({
            "symbol": row["symbol"],
            "company_name": row.get("company_name", ""),
            "exchange": row.get("exchange", "NSE"),
            "sector": row.get("sector", ""),
        })

    return results


def render_index_cards() -> None:
    """Render the live index cards row."""
    from ui.theme import metric_card

    indices = get_indices_data()

    cols = st.columns(len(indices))
    for i, (name, data) in enumerate(indices.items()):
        is_live = data.get("live", False)
        display_name = name.upper().replace("NIFTYMIDCAP", "MIDCAP 150")
        badge = "🟢 LIVE" if is_live else "⚪ offline"

        if not is_live:
            value_str = "—"
            delta_str = ""
            delta_type = "neutral"
        else:
            change = data.get("change", 0.0) or 0.0
            delta_type = "up" if change >= 0 else "down"
            delta_str = format_change(change, price=data["value"])
            value_str = f"{data['value']:,.2f}"

        with cols[i]:
            st.markdown(
                metric_card(
                    label=f"{display_name}",
                    value=value_str,
                    delta=delta_str,
                    delta_type=delta_type,
                ),
                unsafe_allow_html=True,
            )
            st.caption(badge)


def section_header(title: str, icon: str = "") -> None:
    """
    Render a section header.

    `icon` is accepted (and ignored) so the existing emoji call sites keep
    working — the design system uses one typographic heading style, not emoji.
    """
    st.markdown(section_head(title), unsafe_allow_html=True)


def render_coming_soon(title: str) -> None:
    """Render a placeholder for not-yet-implemented sections."""
    st.markdown(f"### {title}")
    st.markdown(
        f"<div style='text-align:center; color:{PALETTE['haze']}; "
        f"padding:3rem; border:1px dashed {PALETTE['grid']}; "
        f"border-radius:12px; margin:1rem 0;'>"
        f"This section is under construction.<br>"
        f"<span style='font-size:0.8rem;'>Part of the Phase 5 build-out.</span>"
        f"</div>",
        unsafe_allow_html=True,
    )


def get_db_status() -> dict:
    """Check database and ingestion status."""
    status = {"db_exists": False, "symbol_count": 0, "price_count": 0}

    try:
        if config.db_path.exists():
            status["db_exists"] = True
            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) as c FROM symbol_master")
                row = cursor.fetchone()
                status["symbol_count"] = row["c"] if row else 0

                cursor.execute("SELECT COUNT(*) as c FROM prices_daily")
                row = cursor.fetchone()
                status["price_count"] = row["c"] if row else 0
    except Exception:
        pass

    return status


__all__ = [
    "format_number",
    "format_cr",
    "color_for_value",
    "delta_html",
    "change_mode",
    "format_change",
    "render_change_toggle",
    "get_symbol_master",
    "get_indices_data",
    "search_symbols",
    "render_index_cards",
    "section_header",
    "render_coming_soon",
    "get_db_status",
]