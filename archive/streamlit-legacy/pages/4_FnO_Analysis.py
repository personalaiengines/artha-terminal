"""
ARTHA Terminal - F&O Analysis page
Daily options game plan for NIFTY 50 / BANK NIFTY / SENSEX: bias, key levels,
OI structure, expected move, and an educational strategy concept.

All numbers are deterministic (services.fno_analysis) from the live option chain.
Nothing here is a buy/sell call — the same SEBI-safe framing as the rest of ARTHA.

The "Key Levels" table is exactly what gets drawn on TradingView — but that draw
runs on the HOST (daily task + scripts/draw_now.py), not from this Docker-hosted
UI, since a container can't reach the host's TradingView CDP debug port.
"""

import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import sys
from pathlib import Path
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ui.theme import GLOBAL_CSS, SEBI_DISCLAIMER, metric_card, PALETTE
from ui.utils import section_header, render_change_toggle
from ui.components import oi_by_strike_chart
from ui.components.charts import lightweight_candles_html
from services.fno_service import (
    build_game_plan, get_index_intraday, get_index_history, INDEXES, INDEX_NAMES,
)
from services.fno_narrative import get_fno_narrative

st.set_page_config(
    page_title="F&O Analysis | ARTHA Terminal",
    page_icon=":material/bolt:",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(GLOBAL_CSS, unsafe_allow_html=True)
render_change_toggle()

_BIAS = {
    "BULLISH": (PALETTE["surge"], "up"),
    "BEARISH": (PALETTE["flare"], "down"),
    "NEUTRAL": (PALETTE["haze"], "neutral"),
}
_KIND_COLOR = {
    "resistance": PALETTE["flare"], "support": PALETTE["surge"],
    "maxpain": PALETTE["laser"], "range": PALETTE["volt"], "pivot": PALETTE["haze"],
}


@st.cache_data(ttl=300, show_spinner=False)
def _plan(index: str) -> dict:
    """Cached game plan (5 min). Cleared by the Refresh button."""
    return build_game_plan(index)


# Timeframe -> (Upstox base interval, history lookback days, pandas resample rule).
# History is fetched at `base` and, for intraday bases, merged with today's live
# feed, then resampled to the target — so every timeframe streams months of past
# bars like a real TradingView chart, not just the current session.
# Lookbacks stay within Upstox's per-interval range caps (1minute ≈ 1 month).
_TF_CFG = {
    "1m":  ("1minute",  10,   None),
    "5m":  ("1minute",  20,   "5min"),
    "15m": ("1minute",  365,  "15min"),   # ~1 year (paged 1-min behind the scenes)
    "30m": ("30minute", 400,  None),      # ~1 year+
    "1D":  ("day",      420,  None),
    "1W":  ("week",     1200, None),
    "1M":  ("month",    2500, None),
}
_TF_OPTIONS = list(_TF_CFG)
_LIVE_BASES = ("1minute", "30minute")   # bases that get today's intraday merged in
_LEVEL_KINDS = list(_KIND_COLOR)        # resistance/support/maxpain/range/pivot


@st.cache_data(ttl=1800, show_spinner=False)
def _hist(index: str, base: str, days: int) -> list[list]:
    """Historical candles at `base` interval (30-min cache — T-1 data is static)."""
    return get_index_history(index, base, days)


@st.cache_data(ttl=15, show_spinner=False)
def _intra(index: str, base: str) -> list[list]:
    """Today's live intraday candles at `base` (15s cache → chart moves live)."""
    return get_index_intraday(index, base)


def _market_open() -> bool:
    """IST weekday, 09:15–15:30 — drives the live auto-refresh cadence."""
    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    if now.weekday() >= 5:
        return False
    return dtime(9, 15) <= now.time() <= dtime(15, 30)


def _series_df(index: str, tf: str) -> pd.DataFrame:
    """Full candle series for `tf`: history + today's live (intraday bases), merged,
    deduped by timestamp, sorted chronologically, then resampled to the target."""
    base, days, rule = _TF_CFG[tf]
    rows = list(_hist(index, base, days))
    if base in _LIVE_BASES:
        rows += _intra(index, base)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume", "oi"])
    # ISO timestamps share one exchange offset → lexical sort == chronological.
    df = df.drop_duplicates("date").sort_values("date").reset_index(drop=True)
    if not rule:
        return df
    d = df.copy()
    d["date"] = pd.to_datetime(d["date"])
    out = (d.set_index("date")
             .resample(rule)
             .agg({"open": "first", "high": "max", "low": "min", "close": "last"})
             .dropna())
    return out.reset_index()


def _live_chart(index: str):
    """Interactive TradingView candlestick (crosshair, pan, zoom) with the F&O key
    levels overlaid as labelled price lines. Auto-refreshes (see run_every at the
    call site) — each refresh rebuilds the chart, so live polling resets pan/zoom."""
    plan = _plan(index)
    tf = st.session_state.get(f"tf_{index}", "1m")
    df = _series_df(index, tf)
    sel = st.session_state.get(f"lvl_{index}", _LEVEL_KINDS)
    levels = [l for l in (plan.get("levels", []) if plan.get("ok") else [])
              if l.get("kind") in sel]
    html = lightweight_candles_html(
        df, levels, _KIND_COLOR,
        height=470, title=f"{INDEX_NAMES.get(index, index)} · {tf}",
    )
    components.html(html, height=490, scrolling=False)
    if df.empty:
        st.caption("No candles (market pre-open with no history, or no Upstox token).")
    ts = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%H:%M:%S")
    live = _market_open()
    st.caption(
        f"{'🟢 Live' if live else '⚪ Market closed'} · {len(df)} bars · {ts} IST"
        f" · drag to pan, scroll to zoom"
    )


def _render_metrics(plan: dict):
    bias = plan["bias"]
    bias_color, bias_delta = _BIAS.get(bias["label"], (PALETTE["haze"], "neutral"))
    em = plan.get("expected_move") or {}

    cols = st.columns(6)
    cells = [
        ("Spot", f"{plan['spot']:,.1f}", "", "neutral"),
        ("Bias", bias["label"], f"score {bias['score']}/100", bias_delta),
        ("PCR (OI)", f"{plan['pcr_oi']:.2f}" if plan['pcr_oi'] else "—", "", "neutral"),
        ("Max Pain", f"{plan['max_pain']:,.0f}" if plan['max_pain'] else "—", "", "neutral"),
        ("ATM IV", f"{plan['atm_iv']:.1f}%" if plan['atm_iv'] else "—", "", "neutral"),
        ("India VIX", f"{plan['india_vix']:.2f}" if plan.get('india_vix') else "—", "", "neutral"),
    ]
    for col, (label, value, delta, dtype) in zip(cols, cells):
        with col:
            st.markdown(metric_card(label, value, delta, dtype), unsafe_allow_html=True)

    if em:
        st.markdown(
            f"<div style='color:{PALETTE['haze']}; font-size:0.85rem; margin-top:0.5rem;'>"
            f"Expected move to expiry <b style='color:{PALETTE['volt']};'>±{em['straddle']:,.0f}"
            f"</b> ({em.get('pct', 0):.1f}%) → range "
            f"<b style='color:{PALETTE['frost']};'>{em['lower']:,.0f} – {em['upper']:,.0f}</b> "
            f"· expiry {plan.get('expiry','—')}</div>",
            unsafe_allow_html=True,
        )


def _render_strategy(plan: dict):
    strat = plan["strategy"]
    anchors = strat.get("anchors", {})
    anchor_txt = " · ".join(
        f"{k.replace('_', ' ')}: {v:,.0f}" for k, v in anchors.items() if v is not None
    )
    st.markdown(
        f"<div class='panel' style='border-left:3px solid {PALETTE['laser']};'>"
        f"<div style='font-family:Inter; font-size:1.05rem; font-weight:700; "
        f"color:{PALETTE['frost']};'>💡 {strat['name']} "
        f"<span style='font-size:0.7rem; color:{PALETTE['haze']};'>· IV regime: "
        f"{strat['iv_regime']}</span></div>"
        f"<div style='color:{PALETTE['haze']}; font-size:0.9rem; margin-top:0.4rem;'>"
        f"{strat['note']}</div>"
        f"<div style='color:{PALETTE['volt']}; font-family:JetBrains Mono; font-size:0.8rem; "
        f"margin-top:0.5rem;'>Strike anchors → {anchor_txt or '—'}</div>"
        f"<div style='color:{PALETTE['haze']}; font-size:0.72rem; margin-top:0.5rem;'>"
        f"Educational strategy concept, not a trade recommendation.</div></div>",
        unsafe_allow_html=True,
    )


def _render_bias_drivers(plan: dict):
    drivers = plan["bias"].get("drivers", [])
    if not drivers:
        return
    with st.expander("Why this bias? (deterministic drivers)", expanded=False):
        for d in drivers:
            delta = d["delta"]
            color = PALETTE["surge"] if delta > 0 else PALETTE["flare"] if delta < 0 else PALETTE["haze"]
            st.markdown(
                f"<div style='display:flex; justify-content:space-between; "
                f"padding:0.3rem 0; border-bottom:1px solid {PALETTE['grid']};'>"
                f"<span style='color:{PALETTE['frost']};'>{d['name']}</span>"
                f"<span style='color:{PALETTE['haze']}; font-size:0.85rem;'>{d['detail']}</span>"
                f"<span style='color:{color}; font-family:JetBrains Mono; font-weight:600;'>"
                f"{delta:+}</span></div>",
                unsafe_allow_html=True,
            )
        st.caption("Score starts at 50 (neutral); drivers push it up (bullish) or down (bearish).")


def _render_levels(plan: dict):
    levels = plan.get("levels", [])
    if not levels:
        st.info("No levels computed.")
        return
    df = pd.DataFrame(levels).sort_values("price", ascending=False)
    df = df.rename(columns={"label": "Level", "price": "Price", "kind": "Type"})
    st.dataframe(
        df[["Level", "Price", "Type"]],
        width="stretch", hide_index=True,
        column_config={"Price": st.column_config.NumberColumn(format="%.1f")},
    )
    st.caption("These are exactly the horizontal levels the TradingView bridge draws.")


def _render_tv_guidance(index: str):
    """
    ARTHA runs in Docker; TradingView Desktop and its CDP debug port live on the
    HOST. A container can't reach 127.0.0.1:9222 on the host, so live drawing
    can't happen from this UI — it runs on the host instead (fully automated
    daily, plus an on-demand script). This panel explains that rather than
    offering a button that would only ever dry-run.
    """
    st.markdown(
        f"<div class='panel' style='border-left:3px solid {PALETTE['volt']};'>"
        f"<div style='font-family:Inter; font-weight:700; color:{PALETTE['frost']};'>"
        f"📌 Drawing on TradingView runs on your PC, not in this dashboard</div>"
        f"<div style='color:{PALETTE['haze']}; font-size:0.85rem; margin-top:0.4rem;'>"
        f"ARTHA runs in Docker here; TradingView Desktop runs on your host machine. "
        f"A container can't reach the host's TradingView debug port, so drawing is "
        f"handled outside this UI:</div>"
        f"<ul style='color:{PALETTE['haze']}; font-size:0.85rem; margin-top:0.4rem;'>"
        f"<li><b style='color:{PALETTE['surge']};'>Automatic</b> — the "
        f"<code>ARTHA F&amp;O Daily Draw</code> Windows task redraws all three "
        f"indices every weekday, ~08:00 IST.</li>"
        f"<li><b style='color:{PALETTE['frost']};'>On demand</b> — run this on the "
        f"host (TradingView must be open via the <i>TradingView (Debug)</i> "
        f"shortcut):</li></ul>"
        f"<code style='display:block; background:{PALETTE['abyss']}; padding:0.5rem; "
        f"border-radius:6px; color:{PALETTE['surge']}; font-size:0.8rem;'>"
        f"venv\\Scripts\\python.exe scripts\\draw_now.py {index}</code>"
        f"</div>",
        unsafe_allow_html=True,
    )


def render_index(index: str):
    plan = _plan(index)
    if not plan.get("ok"):
        st.warning(
            f"Couldn't build the {INDEX_NAMES.get(index, index)} game plan: "
            f"{plan.get('error', 'unknown error')}. "
            f"Needs a valid Upstox analytics token with F&O market-data access."
        )
        return

    _render_metrics(plan)
    st.markdown("")

    # Live price chart with the key levels drawn on it — the native, CDP-free
    # answer to "see the chart move with support/resistance during market hours".
    section_header("Live Price + Key Levels", "📈")
    tfcol, lvlcol, livecol = st.columns([1, 2, 1])
    with tfcol:
        st.selectbox("Timeframe", _TF_OPTIONS, key=f"tf_{index}",
                     help="Each timeframe streams history: 15m/30m reach ~1 year, "
                          "1D/1W/1M multi-year. 1m/5m are recent days.")
    with lvlcol:
        st.multiselect("Show levels", _LEVEL_KINDS, default=_LEVEL_KINDS, key=f"lvl_{index}",
                       help="Uncheck any level type you don't want drawn on the chart.")
    with livecol:
        st.markdown("<div style='height:1.7rem;'></div>", unsafe_allow_html=True)
        live_on = st.checkbox(
            "🔴 Live refresh (15s)", value=_market_open(), key=f"liveref_{index}",
            help="On: poll every 15s (rebuilds the chart, resets pan/zoom). "
                 "Off: keep your zoom/pan and inspect freely. (Intraday only.)",
        )
    tf_now = st.session_state.get(f"tf_{index}", "1m")
    # Only poll live when today's intraday feed is part of this timeframe.
    intraday = _TF_CFG[tf_now][0] in _LIVE_BASES
    run = 15 if (live_on and _market_open() and intraday) else None
    st.fragment(_live_chart, run_every=run)(index)
    st.markdown("")

    left, right = st.columns([3, 2])
    with left:
        section_header("Open Interest Structure", "📊")
        fig = oi_by_strike_chart(plan.get("strikes", []), spot=plan["spot"])
        st.plotly_chart(fig, width="stretch")
    with right:
        section_header("Strategy Concept", "🎯")
        _render_strategy(plan)
        _render_bias_drivers(plan)

    section_header("Key Levels", "📐")
    _render_levels(plan)

    # === AI Analysis (Claude · grounded on the numbers above) ===
    section_header("AI Analysis (Claude · grounded)", "🧠")
    st.caption("A senior-strategist read written by Claude strictly from the verified "
               "figures above — educational, not investment advice.")
    nkey = f"fno_narrative_{index}"
    if st.button("🚀 Generate AI Analysis", key=f"gen_{index}", type="primary"):
        with st.spinner("Claude is reading the option-chain structure…"):
            st.session_state[nkey] = get_fno_narrative(plan)
    narr = st.session_state.get(nkey)
    if narr:
        if narr.get("ok"):
            st.markdown(narr["markdown"])
            st.caption(f"🤖 Generated by `{narr.get('model', '')}` · grounded strictly on the "
                       f"verified figures above · educational, not investment advice.")
        else:
            st.warning("The analysis model is busy or not configured — the data panels above "
                       "are complete regardless. (Set OPENROUTER_API_KEY / NVIDIA_API_KEY.)")

    _render_tv_guidance(index)

    st.caption(f"Generated {plan.get('generated_ist', '')[:19].replace('T', ' ')} IST")


# ============================================
# Page
# ============================================

st.markdown("# F&O analysis")
st.markdown(
    f"<p style='color:{PALETTE['haze']};'>Daily options game plan for NIFTY 50, BANK NIFTY "
    f"and SENSEX — bias, key levels, OI structure, expected move and an educational "
    f"strategy concept. Deterministic math on the live option chain.</p>",
    unsafe_allow_html=True,
)

if st.button("🔄 Refresh all", help="Recompute all three game plans now"):
    _plan.clear()
    st.rerun()

tabs = st.tabs([INDEX_NAMES[i] for i in INDEXES])
for tab, index in zip(tabs, INDEXES):
    with tab:
        with st.spinner(f"Building {INDEX_NAMES[index]} game plan…"):
            render_index(index)

st.markdown("---")
st.markdown(SEBI_DISCLAIMER, unsafe_allow_html=True)
