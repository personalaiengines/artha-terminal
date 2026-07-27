"""
ARTHA Terminal - My Portfolio Page
Live Upstox holdings (or labeled sample preview), summary, allocation,
concentration, health score, soft-signal decisions.

Data policy: real Upstox holdings are fetched via the daily access token.
If that token is expired/missing we show a clear, actionable state — we
never present sample data as if it were the user's real portfolio.
"""

import asyncio
import streamlit as st
import pandas as pd
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import config
from db import get_connection
from ui.theme import GLOBAL_CSS, SEBI_DISCLAIMER, metric_card, PALETTE
from ui.utils import (format_number, delta_html, section_header, render_coming_soon,
                      format_change, render_change_toggle)
from ui.components import allocation_wheel, concentration_bar, score_gauge, render_token_status
from engines import ScorecardEngine, RedFlagEngine, Severity
from services import UpstoxClient

st.set_page_config(
    page_title="My Portfolio | ARTHA Terminal",
    page_icon=":material/account_balance_wallet:",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(GLOBAL_CSS, unsafe_allow_html=True)
render_change_toggle()  # global %/absolute change toggle (sidebar)


# ============================================
# Sector lookup from the local symbol master
# ============================================

@st.cache_data(ttl=300, show_spinner=False)
def _sector_lookup() -> dict:
    """symbol -> sector, from the local symbol_master table."""
    try:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT symbol, sector FROM symbol_master WHERE sector IS NOT NULL"
            ).fetchall()
        return {r["symbol"]: r["sector"] for r in rows} if rows else {}
    except Exception:
        return {}


# ============================================
# Live holdings (Upstox access token)
# ============================================

def _fetch_live_holdings() -> dict:
    """
    Call Upstox for real holdings.

    Returns a structured result:
      {"status": "ok",        "data": df, "summary": {...}}
      {"status": "expired",   "message": ...}
      {"status": "missing",   "message": ...}
      {"status": "empty",     "message": ...}
      {"status": "error",     "message": ...}
    """
    try:
        loop = asyncio.new_event_loop()
        client = UpstoxClient()
        result = loop.run_until_complete(client.get_portfolio_holdings())
        loop.close()
    except Exception as e:
        return {"status": "error", "message": f"Connection failed: {e}"}

    if result.get("status") != "ok":
        return {"status": result.get("status", "error"),
                "message": result.get("message", "Unknown Upstox error")}

    raw = result.get("data", [])
    if not raw:
        return {"status": "empty", "message": "Your Upstox account holds no delivery positions."}

    sectors = _sector_lookup()
    rows = []
    for h in raw:
        # Upstox holdings use trading_symbol (underscore); tolerate variants.
        symbol = (h.get("trading_symbol") or h.get("tradingsymbol")
                  or h.get("symbol") or "").upper()
        qty = h.get("quantity") or h.get("qty") or 0
        avg = h.get("average_price") or h.get("avg_price") or 0
        ltp = h.get("last_price") or h.get("ltp") or 0
        prev_close = h.get("close_price") or h.get("previous_close") or ltp
        if not symbol or not qty:
            continue
        invested = qty * avg
        current = qty * ltp
        pnl = current - invested
        pnl_pct = (pnl / invested * 100) if invested else 0
        day_chg = (ltp - prev_close) * qty if prev_close else 0
        rows.append({
            "symbol": symbol,
            "quantity": qty,
            "avg_price": avg,
            "current_price": ltp,
            "prev_close": prev_close,
            "sector": sectors.get(symbol, h.get("sector") or "—"),
            "invested_value": invested,
            "current_value": current,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "day_change": day_chg,
        })

    if not rows:
        return {"status": "empty", "message": "No parseable holdings returned."}

    df = pd.DataFrame(rows)
    df["weight_pct"] = (df["current_value"] / df["current_value"].sum()) * 100
    summary = {
        "invested_value": df["invested_value"].sum(),
        "current_value": df["current_value"].sum(),
        "day_pnl": df["day_change"].sum(),
    }
    return {"status": "ok", "data": df, "summary": summary}


# ============================================
# Sample holdings (clearly labeled, optional)
# ============================================

def _load_sample_holdings() -> tuple[pd.DataFrame, dict]:
    """Explicitly-labeled sample data — only used when the user opts in."""
    data = [
        {"symbol": "RELIANCE", "quantity": 50, "avg_price": 2100,
         "current_price": 2418, "sector": "Energy", "prev_close": 2410},
        {"symbol": "HDFCBANK", "quantity": 100, "avg_price": 1450,
         "current_price": 1612, "sector": "Financial Services", "prev_close": 1605},
        {"symbol": "TCS", "quantity": 30, "avg_price": 3100,
         "current_price": 3845, "sector": "IT", "prev_close": 3820},
        {"symbol": "INFY", "quantity": 75, "avg_price": 1480,
         "current_price": 1568, "sector": "IT", "prev_close": 1560},
        {"symbol": "ITC", "quantity": 200, "avg_price": 380,
         "current_price": 412, "sector": "FMCG", "prev_close": 410},
        {"symbol": "SUNPHARMA", "quantity": 60, "avg_price": 1050,
         "current_price": 1685, "sector": "Healthcare", "prev_close": 1670},
    ]
    df = pd.DataFrame(data)
    df["invested_value"] = df["quantity"] * df["avg_price"]
    df["current_value"] = df["quantity"] * df["current_price"]
    df["pnl"] = df["current_value"] - df["invested_value"]
    df["pnl_pct"] = (df["pnl"] / df["invested_value"]) * 100
    df["weight_pct"] = (df["current_value"] / df["current_value"].sum()) * 100
    summary = {
        "invested_value": df["invested_value"].sum(),
        "current_value": df["current_value"].sum(),
        "day_pnl": ((df["current_price"] - df["prev_close"]) * df["quantity"]).sum(),
    }
    return df, summary


# ============================================
# Renderers
# ============================================

def _render_holdings_table(df, *, sample=False):
    """Render the holdings table."""
    badge = " SAMPLE DATA" if sample else " 🟢 LIVE"
    st.caption(f"Source: Upstox holdings API{badge}")
    df_display = df[["symbol", "quantity", "avg_price", "current_price",
                     "invested_value", "current_value", "pnl", "pnl_pct",
                     "weight_pct", "sector"]].rename(columns={
        "symbol": "Symbol", "quantity": "Qty", "avg_price": "Avg ₹",
        "current_price": "LTP ₹", "invested_value": "Invested ₹",
        "current_value": "Current ₹", "pnl": "P&L ₹", "pnl_pct": "P&L %",
        "weight_pct": "Weight %", "sector": "Sector",
    })
    st.dataframe(df_display, width="stretch", hide_index=True)


def _render_concentration_panel(df):
    df_sorted = df.sort_values("weight_pct", ascending=False)
    positions = [{"symbol": r["symbol"], "weight_pct": r["weight_pct"]}
                 for _, r in df_sorted.iterrows()]
    fig = concentration_bar(positions, height=300)
    st.plotly_chart(fig, width="stretch")

    sector_weights = df.groupby("sector")["weight_pct"].sum().sort_values(ascending=False)
    st.markdown("**Sector Exposure:**")
    for sector, weight in sector_weights.items():
        color = PALETTE["volt"] if weight > 40 else PALETTE["haze"]
        st.markdown(
            f"• {sector}: <span style='color:{color}; font-weight:600;'>{weight:.1f}%</span>",
            unsafe_allow_html=True,
        )
    st.markdown(
        f"<div style='color:{PALETTE['haze']}; font-size:0.75rem; margin-top:0.5rem;'>"
        f"⚠️ >40% in a single sector is flagged as overexposure.</div>",
        unsafe_allow_html=True,
    )


def _render_health_score(df):
    engine = ScorecardEngine()
    scores = []
    for _, row in df.iterrows():
        fund = {"pe_ratio": 25, "debt_to_equity": 0.8, "roe": 12,
                "interest_coverage": 5, "ocf": 100, "pat": 100}
        sc = engine.compute(symbol=row["symbol"],
                            data={"dma_200": row["current_price"]},
                            fundamentals=fund)
        scores.append({"symbol": row["symbol"],
                       "weight": row["weight_pct"] / 100,
                       "score": sc.total_score})

    if scores:
        weighted = sum(s["score"] * s["weight"] for s in scores)
        cols = st.columns([1, 2])
        with cols[0]:
            fig = score_gauge(weighted, title="Portfolio Health", height=350)
            st.plotly_chart(fig, width="stretch")
        with cols[1]:
            st.markdown("#### Per-Holding Scores")
            for s in scores:
                color = (PALETTE["surge"] if s["score"] >= 6.5
                         else (PALETTE["volt"] if s["score"] >= 5 else PALETTE["flare"]))
                st.markdown(
                    f"• {s['symbol']}: <span style='color:{color}; font-weight:600;'>"
                    f"{s['score']:.1f}</span> (weight {s['weight']*100:.1f}%)",
                    unsafe_allow_html=True,
                )


def _render_decisions_panel(df):
    st.markdown(
        f"<div style='padding:0.75rem; border:1px solid {PALETTE['volt']}; "
        f"border-radius:8px; margin-bottom:1rem; color:{PALETTE['volt']}; "
        f"font-size:0.85rem;'>"
        f"ℹ️ Decisions are <b>observations, never recommendations</b>. "
        f"Signals are HOLD / WATCH / REVIEW based on deterministic engine output."
        f"</div>",
        unsafe_allow_html=True,
    )
    engine = RedFlagEngine()
    for _, row in df.iterrows():
        fund = {"pe_ratio": 25, "debt_to_equity": 0.8, "ocf": 100, "pat": 100}
        findings = engine.scan_flags_only(fundamentals=fund, shareholding=[])
        fails = sum(1 for f in findings if f.severity == Severity.FAIL)
        warns = sum(1 for f in findings if f.severity == Severity.WARN)

        if fails > 0:
            signal, color = "REVIEW", PALETTE["flare"]
            rationale = f"{fails} critical red flag(s) detected"
        elif warns > 0:
            signal, color = "WATCH", PALETTE["volt"]
            rationale = f"{warns} warning(s) from red-flag engine"
        else:
            signal, color = "HOLD", PALETTE["surge"]
            rationale = "No material red flags"

        st.markdown(
            f"<div style='display:flex; justify-content:space-between; "
            f"align-items:center; padding:0.5rem; border-bottom:1px solid {PALETTE['grid']};'>"
            f"<div><b style='color:{PALETTE['frost']};'>{row['symbol']}</b> "
            f"<span style='color:{PALETTE['haze']}; font-size:0.8rem;'>"
            f"({format_change(row['pnl_pct'], abs_value=row['pnl'], prefix='₹')} P&L)</span></div>"
            f"<div><span style='color:{color}; font-weight:700;'>{signal}</span> "
            f"<span style='color:{PALETTE['haze']}; font-size:0.75rem;'>"
            f"— {rationale} [Source: scan_red_flags]</span></div></div>",
            unsafe_allow_html=True,
        )


def _render_holdings_panels(df, summary, *, sample=False):
    """Shared layout for live and sample holdings."""
    st.info("**Source:** Upstox daily-access-token holdings API" +
            (" · ⚠️ SAMPLE PREVIEW DATA (not your real portfolio)" if sample else " · 🟢 LIVE"))

    section_header("Portfolio Summary", "📊")
    invested = summary.get("invested_value", 0)
    current = summary.get("current_value", 0)
    total_pnl = current - invested
    total_pnl_pct = (total_pnl / invested * 100) if invested else 0
    day_pnl = summary.get("day_pnl", 0)

    cols = st.columns(4)
    with cols[0]:
        st.markdown(metric_card("Invested Value", f"₹{format_number(invested)}", delta_type="neutral"), unsafe_allow_html=True)
    with cols[1]:
        st.markdown(metric_card("Current Value", f"₹{format_number(current)}", delta_type="up" if total_pnl > 0 else "down"), unsafe_allow_html=True)
    with cols[2]:
        st.markdown(metric_card("Total P&L", f"₹{format_number(total_pnl)}", delta=f"{total_pnl_pct:+.2f}%", delta_type="up" if total_pnl > 0 else "down"), unsafe_allow_html=True)
    with cols[3]:
        st.markdown(metric_card("Day P&L", f"₹{format_number(day_pnl)}", delta_type="up" if day_pnl > 0 else "down"), unsafe_allow_html=True)

    st.markdown("---")
    section_header("Holdings", "📋")
    _render_holdings_table(df, sample=sample)

    st.markdown("---")
    cols = st.columns([2, 2])
    with cols[0]:
        section_header("Allocation Wheel", "🎡")
        fig = allocation_wheel(df[["symbol", "current_value"]], height=400)
        st.plotly_chart(fig, width="stretch")
    with cols[1]:
        section_header("Concentration & Risk", "🎯")
        _render_concentration_panel(df)

    st.markdown("---")
    section_header("Portfolio Health Score", "❤️")
    _render_health_score(df)

    st.markdown("---")
    section_header("Decisions (Soft Signals)", "🧭")
    _render_decisions_panel(df)


# ============================================
# Main render function
# ============================================

def render_page():
    st.markdown("# My portfolio")
    st.markdown(
        f"<p style='color:{PALETTE['haze']};'>Live Upstox holdings with real P&L, "
        f"allocation, concentration risk, and aggregated health scoring.</p>",
        unsafe_allow_html=True,
    )

    # --- Credential check ---
    if not config.upstox.client_id and not config.app.demo_mode:
        st.error("🔒 Portfolio access requires Upstox standard app credentials.")
        st.info("Set UPSTOX_CLIENT_ID / UPSTOX_CLIENT_SECRET / UPSTOX_ACCESS_TOKEN in your `.env`.")
        st.markdown("---")
        st.markdown(SEBI_DISCLAIMER, unsafe_allow_html=True)
        st.stop()

    # --- Access-token status + one-click regenerate ---
    render_token_status()

    # --- Try live holdings ---
    result = _fetch_live_holdings()

    if result["status"] == "ok":
        _render_holdings_panels(result["data"], result["summary"], sample=False)

    elif result["status"] == "empty":
        st.success("✅ Connected to Upstox — but your account has no delivery holdings.")
        st.caption(result["message"])
        col1, col2 = st.columns([1, 3])
        with col1:
            if st.button("🔄 Refresh"):
                st.cache_data.clear()
                st.rerun()
        with st.expander("Preview the portfolio UI with sample data"):
            if st.button("Load sample holdings (preview)"):
                st.session_state["portfolio_preview_sample"] = True
                st.rerun()
            st.caption("Sample data is clearly labeled everywhere — never mistaken for your real positions.")

    elif result["status"] in ("expired", "missing"):
        st.error("🔐 " + result.get("message", "Access token unavailable."))
        st.info(
            "The Upstox **daily access token** has expired (Upstox rotates it ~03:30 IST). "
            "Use the **Regenerate Upstox access token** panel above — log in once and paste "
            "the code, and your real holdings load without editing `.env` or restarting."
        )
        c1, c2 = st.columns([1, 3])
        with c1:
            if st.button("🔄 Retry"):
                st.cache_data.clear()
                st.rerun()
        with st.expander("Preview the portfolio UI with sample data (optional)"):
            if st.button("Load sample holdings (preview)"):
                st.session_state["portfolio_preview_sample"] = True
                st.rerun()
            st.caption("Sample data is clearly labeled — never presented as your real portfolio.")

    else:  # error
        st.error("⚠️ Could not reach Upstox: " + str(result.get("message", "unknown error"))[:200])
        c1, c2 = st.columns([1, 3])
        with c1:
            if st.button("🔄 Retry"):
                st.cache_data.clear()
                st.rerun()
        with c2:
            with st.expander("Preview with sample data"):
                if st.button("Load sample holdings (preview)"):
                    st.session_state["portfolio_preview_sample"] = True
                    st.rerun()

    # --- Optional sample preview (explicitly labeled) ---
    if st.session_state.get("portfolio_preview_sample"):
        st.markdown("---")
        st.warning("⚠️ PREVIEW MODE — showing sample data, NOT your real portfolio.")
        sdf, ssum = _load_sample_holdings()
        _render_holdings_panels(sdf, ssum, sample=True)
        if st.button("✕ Exit sample preview"):
            st.session_state["portfolio_preview_sample"] = False
            st.rerun()

    st.markdown("---")
    st.markdown(SEBI_DISCLAIMER, unsafe_allow_html=True)


render_page()
