"""
ARTHA Terminal - Index Levels panel
Senior-analyst technical read for NIFTY / BANK NIFTY / SENSEX: current level,
bias, pivot, a support/resistance ladder, and a rule-derived commentary.

Levels are standard daily pivot points computed from real OHLC — technical
reference levels, not buy/sell advice (see the page's SEBI disclaimer).
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import streamlit as st

from services.levels import get_pivot_bases, get_live_prices, analyze
from ui.theme import PALETTE, clean_html, section_head


_PRICE_REFRESH = 15      # fragment cadence (s) — Upstox index quote, real-time
_PRICE_TTL = 10          # keep under _PRICE_REFRESH so each tick gets fresh data (avoids the 2× beat)
_PIVOT_TTL = 30 * 60     # pivots are fixed for the day — cache 30 min


@st.cache_data(ttl=_PIVOT_TTL, show_spinner=False)
def _load_pivots() -> dict:
    """Daily pivot ladders — static through the session, cached 30 min."""
    return get_pivot_bases()


@st.cache_data(ttl=_PRICE_TTL, show_spinner=False)
def _load_prices() -> dict:
    """Live index prices — cached just under the refresh cadence."""
    return get_live_prices()


_BIAS = {
    "bullish": (PALETTE["surge"], "▲ Bullish"),
    "bearish": (PALETTE["flare"], "▼ Bearish"),
    "neutral": (PALETTE["haze"], "▬ Neutral"),
}
_ZONE = {
    "breakout": (PALETTE["surge"], "BREAKOUT"),
    "breakdown": (PALETTE["flare"], "BREAKDOWN"),
    "in-range": (PALETTE["haze"], "IN RANGE"),
}


def _level_pills(items: list, color: str, price: float, kind: str) -> str:
    """
    Render an S or R ladder as pills, dimming levels the price has already passed
    (a resistance below price, or a support above price, is 'crossed').
    """
    out = []
    for label, val in items:
        crossed = (val < price) if kind == "resistance" else (val > price)
        opacity = "0.35" if crossed else "1"
        out.append(
            f"<span style='display:inline-block; background:{color}18; color:{color}; "
            f"border:1px solid {color}55; border-radius:6px; padding:2px 8px; margin:2px; "
            f"font-family:JetBrains Mono; font-size:0.72rem; opacity:{opacity};'>"
            f"{label} {val:,.0f}</span>"
        )
    return "".join(out)


def _index_card(x: dict) -> str:
    """Return one index card as an HTML string (joined into a single grid block)."""
    bias_color, bias_label = _BIAS.get(x["bias"], _BIAS["neutral"])
    zone_color, zone_label = _ZONE.get(x["zone"], _ZONE["in-range"])
    live_badge = "🟢 LIVE" if x["live"] else "⚪ delayed"

    ns = x["nearest_support"]
    nr = x["nearest_resistance"]
    ns_str = f"{ns[0]} {ns[1]:,.0f}" if ns else "—"
    nr_str = f"{nr[0]} {nr[1]:,.0f}" if nr else "blue-sky"

    return clean_html(f"""
        <div class="panel" style="padding:1rem 1.2rem;">
          <div style="display:flex; justify-content:space-between; align-items:baseline;">
            <span style="font-family:'Inter'; font-weight:700; font-size:1.05rem;
                         color:{PALETTE['frost']};">{x['name']}</span>
            <span style="font-size:0.62rem; color:{zone_color}; font-weight:700;
                         border:1px solid {zone_color}66; border-radius:6px;
                         padding:1px 7px;">{zone_label}</span>
          </div>
          <div style="display:flex; align-items:baseline; gap:0.6rem; margin:0.3rem 0;">
            <span style="font-family:'JetBrains Mono'; font-size:1.5rem; font-weight:700;
                         color:{PALETTE['frost']};">{x['price']:,.2f}</span>
            <span style="color:{bias_color}; font-weight:700; font-size:0.85rem;">{bias_label}</span>
            <span style="font-size:0.6rem; color:{PALETTE['haze']}; margin-left:auto;">{live_badge}</span>
          </div>
          <div style="font-size:0.72rem; color:{PALETTE['haze']}; margin-bottom:0.4rem;">
            Pivot <span style="color:{PALETTE['volt']}; font-family:JetBrains Mono;">{x['pivot']:,.0f}</span>
            &nbsp;·&nbsp; nearest support
            <span style="color:{PALETTE['surge']};">{ns_str}</span>
            &nbsp;·&nbsp; nearest resistance
            <span style="color:{PALETTE['flare']};">{nr_str}</span>
          </div>
          <div style="margin:0.3rem 0;">
            <div style="font-size:0.62rem; color:{PALETTE['haze']}; text-transform:uppercase;
                        letter-spacing:1px;">Resistance</div>
            {_level_pills(x['resistances'], PALETTE['flare'], x['price'], 'resistance')}
          </div>
          <div style="margin:0.3rem 0;">
            <div style="font-size:0.62rem; color:{PALETTE['haze']}; text-transform:uppercase;
                        letter-spacing:1px;">Support</div>
            {_level_pills(x['supports'], PALETTE['surge'], x['price'], 'support')}
          </div>
          <div style="font-size:0.78rem; color:{PALETTE['frost']}; line-height:1.5;
                      border-top:1px solid {PALETTE['grid']}; margin-top:0.6rem; padding-top:0.6rem;">
            <span style="color:{PALETTE['laser']}; font-weight:600;">Analyst view:</span>
            {x['analyst']}
          </div>
        </div>
        """)


def _pretty_session(iso_date: str) -> str:
    try:
        return date.fromisoformat(iso_date).strftime("%a %d %b")
    except Exception:
        return iso_date


@st.fragment(run_every=_PRICE_REFRESH)
def render_index_levels() -> None:
    """
    Senior-analyst levels board for the three headline indices.

    Auto-refreshes every 60s: pivot LEVELS are fixed for the day (cached 30 min),
    only the live PRICE, bias and analyst read update each tick.
    """
    st.markdown(section_head("Index levels & analyst view"), unsafe_allow_html=True)

    pivots = _load_pivots().get("indices", [])
    if not pivots:
        st.info("Index level data is temporarily unavailable.")
        return

    price_data = _load_prices()
    prices = price_data["prices"]
    live_keys = set(price_data["live_keys"])
    fetched = datetime.fromisoformat(price_data["fetched_ist"])
    session_date = pivots[0].get("session_date", "")

    # Header: two distinct cadences made explicit
    left, right = st.columns([3, 2])
    with left:
        st.markdown(
            f"<div style='font-size:0.72rem; color:{PALETTE['haze']};'>"
            f"Pivot levels fixed for today · basis: last session "
            f"<span style='color:{PALETTE['volt']};'>{_pretty_session(session_date)}</span></div>",
            unsafe_allow_html=True,
        )
    with right:
        st.markdown(
            f"<div style='text-align:right; font-size:0.72rem; color:{PALETTE['haze']};'>"
            f"⟳ price auto-refresh {_PRICE_REFRESH}s · last "
            f"<span style='color:{PALETTE['surge']};'>{fetched:%H:%M:%S IST}</span></div>",
            unsafe_allow_html=True,
        )

    cards = []
    for b in pivots:
        price = prices.get(b["key"]) or b["yf_last"]
        a = analyze(b["name"], price, b["_piv"])
        card = {
            "name": b["name"], "price": round(price, 2), "live": b["key"] in live_keys,
            "pivot": b["pivot"], "resistances": b["resistances"], "supports": b["supports"],
            **a,
        }
        cards.append(_index_card(card))

    # One CSS-grid block (not st.columns) so the fragment updates in place
    # without tearing down column containers each tick — avoids the panel flash.
    st.markdown(
        f"<div style='display:grid; grid-template-columns:repeat({len(pivots)},1fr); "
        f"gap:0.75rem;'>{''.join(cards)}</div>",
        unsafe_allow_html=True,
    )

    st.caption(
        "Support/resistance are classic daily pivot points computed from the last "
        "session's OHLC (technical reference levels, not price targets or buy/sell "
        "advice). Levels update once per day; price & bias refresh live."
    )


__all__ = ["render_index_levels"]
