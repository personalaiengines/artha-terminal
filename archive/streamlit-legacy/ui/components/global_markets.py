"""
ARTHA Terminal - Global Markets panel
Auto-refreshing world board: international indices + commodities with live
prices, per-market open/closed status, and a visible last-refreshed clock.

Refreshes itself on a short timer via st.fragment(run_every=...) without
rerunning the rest of the page.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import streamlit as st

from services.global_markets import get_global_board
from services.market_events import get_market_events, get_ai_macro_events
from ui.theme import PALETTE, clean_html, section_head
from ui.utils import format_change


_REFRESH_SECONDS = 30  # fragment cadence (visible refresh)
# Cache TTL must stay BELOW the fragment cadence, else the cache is still valid
# on most ticks and refreshes land every *other* tick (2× the interval).
_BOARD_TTL = 20        # Yahoo tiles are ~15min delayed & fetched per-ticker; keep gentle to avoid throttling
_EVENTS_TTL = 6 * 3600  # events are daily-scale; refresh a few times a day


@st.cache_data(ttl=_BOARD_TTL, show_spinner=False)
def _load_board() -> dict:
    """Cached board fetch — TTL kept under the fragment cadence so each tick is fresh."""
    return get_global_board()


_STATE_STYLE = {
    "open": (PALETTE["surge"], "🟢 OPEN"),
    "closed": (PALETTE["flare"], "🔴 CLOSED"),
    "24h": (PALETTE["volt"], "🟡 24H"),
}


def _tile(row: dict) -> str:
    """Build one market tile as HTML."""
    price = row["price"]
    unit = row["unit"]
    chg = row["change_pct"]
    status = row["status"]

    if price is None:
        value_str = "—"
        chg_str = ""
        chg_color = PALETTE["haze"]
    else:
        value_str = f"{unit}{price:,.2f}"
        if chg is None:
            chg_str, chg_color = "—", PALETTE["haze"]
        else:
            arrow = "▲" if chg >= 0 else "▼"
            chg_color = PALETTE["surge"] if chg >= 0 else PALETTE["flare"]
            chg_str = f"{arrow} {format_change(chg, price=price)}"

    state_color, state_label = _STATE_STYLE.get(
        status["state"], (PALETTE["haze"], status["state"].upper())
    )

    return clean_html(f"""
    <div class="panel" style="padding:0.9rem 1rem; min-height:118px;">
        <div style="display:flex; justify-content:space-between; align-items:baseline;">
            <span style="font-family:'Inter'; font-weight:600;
                         color:{PALETTE['frost']}; font-size:0.95rem;">{row['name']}</span>
            <span style="font-size:0.6rem; color:{state_color};
                         font-weight:700;">{state_label}</span>
        </div>
        <div style="font-family:'JetBrains Mono'; font-size:1.35rem; font-weight:700;
                    color:{PALETTE['frost']}; margin:0.35rem 0 0.1rem;">{value_str}</div>
        <div style="font-family:'JetBrains Mono'; font-size:0.85rem; color:{chg_color};">{chg_str}</div>
        <div style="font-size:0.62rem; color:{PALETTE['haze']}; margin-top:0.35rem;">
            {status['local_time']} · {status['note']}
        </div>
    </div>
    """)


def _grid(rows: list[dict], cols_per_row: int = 4) -> None:
    """
    Render all tiles as ONE CSS-grid HTML block (not st.columns).

    A single element updates in place when the fragment re-runs, so the panel
    doesn't tear down and rebuild column containers each tick — which is what
    caused the whole-panel flash on auto-refresh.
    """
    tiles = "".join(_tile(r) for r in rows)
    st.markdown(
        f"<div style='display:grid; grid-template-columns:repeat({cols_per_row},1fr); "
        f"gap:0.75rem;'>{tiles}</div>",
        unsafe_allow_html=True,
    )


@st.fragment(run_every=_REFRESH_SECONDS)
def render_global_markets() -> None:
    """
    Render the auto-refreshing global markets board.

    Runs on its own short timer (st.fragment) so it updates live without
    rerunning the whole landing page.
    """
    board = _load_board()

    refreshed = datetime.fromisoformat(board["refreshed_at_utc"])
    local = refreshed.astimezone(ZoneInfo("Asia/Kolkata"))

    header_l, header_r = st.columns([3, 2])
    with header_l:
        st.markdown(section_head("Global markets & commodities"), unsafe_allow_html=True)
    with header_r:
        st.markdown(
            f"<div style='text-align:right; font-size:0.72rem; color:{PALETTE['haze']}; "
            f"padding-top:0.9rem;'>⟳ auto-refresh {_REFRESH_SECONDS}s · "
            f"last updated <span style='color:{PALETTE['surge']};'>"
            f"{local:%H:%M:%S} IST</span></div>",
            unsafe_allow_html=True,
        )

    st.markdown(
        f"<div style='color:{PALETTE['haze']}; font-size:0.8rem; margin-bottom:0.5rem;'>"
        f"International indices</div>",
        unsafe_allow_html=True,
    )
    _grid(board["indices"], cols_per_row=4)

    st.markdown(
        f"<div style='color:{PALETTE['haze']}; font-size:0.8rem; "
        f"margin:0.75rem 0 0.5rem;'>Commodities & crypto</div>",
        unsafe_allow_html=True,
    )
    _grid(board["commodities"], cols_per_row=4)

    st.caption(
        "Prices via Yahoo Finance (~15 min delayed). Open/closed reflects each "
        "exchange's real trading calendar, including public holidays."
    )


# ------------------------------------------------------------------
# Market events (one-week lookahead)
# ------------------------------------------------------------------

@st.cache_data(ttl=_EVENTS_TTL, show_spinner="Loading market events…")
def _load_events(symbols: tuple[str, ...], days_ahead: int) -> dict:
    """Cached deterministic events (fast) — keyed on symbols + window."""
    return get_market_events(list(symbols), days_ahead=days_ahead)


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def _load_ai_macro(days_ahead: int) -> dict:
    """AI macro events (slow) — cached a full day ONLY on success. NIM's free
    tier has variable latency, so a failed/timed-out attempt must not be cached
    for 24h (it would strand the user on 'unavailable'); raise so it retries."""
    r = get_ai_macro_events(days_ahead=days_ahead)
    if not r.get("ok"):
        raise RuntimeError("AI macro fetch failed")
    return r


def _safe_ai_macro(days_ahead: int) -> dict:
    try:
        return _load_ai_macro(days_ahead)
    except Exception:
        return {"ok": False, "india": [], "international": []}


_EVENT_STYLE = {
    "holiday": (PALETTE["flare"], "🔴"),
    "earnings": (PALETTE["laser"], "📊"),
    "schedule": (PALETTE["volt"], "🗓️"),
    "macro": (PALETTE["surge"], "🤖"),
}


def _relative_day(d: date, today: date) -> str:
    delta = (d - today).days
    if delta == 0:
        return "Today"
    if delta == 1:
        return "Tomorrow"
    return d.strftime("%a %d %b")


def _event_row(e: dict, today: date) -> str:
    d = date.fromisoformat(e["date"])
    color, icon = _EVENT_STYLE.get(e["kind"], (PALETTE["haze"], "•"))
    rel = _relative_day(d, today)
    is_soon = rel in ("Today", "Tomorrow")
    title = e["title"]
    if e.get("url"):
        title = (f"<a href='{e['url']}' target='_blank' style='color:{PALETTE['frost']}; "
                 f"text-decoration:none; border-bottom:1px dotted {PALETTE['haze']};'>"
                 f"{title} ↗</a>")
    rel_color = color if is_soon else PALETTE["haze"]
    return (
        f"<div style='display:flex; align-items:center; gap:0.6rem; padding:0.45rem 0.6rem; "
        f"border-bottom:1px solid {PALETTE['grid']}44;'>"
        f"<span style='font-size:0.95rem;'>{icon}</span>"
        f"<span style='font-family:JetBrains Mono; font-size:0.68rem; color:{rel_color}; "
        f"min-width:82px; font-weight:{700 if is_soon else 400};'>{rel}</span>"
        f"<span style='color:{PALETTE['frost']}; font-size:0.85rem; font-weight:600;'>{title}</span>"
        f"<span style='color:{PALETTE['haze']}; font-size:0.68rem; margin-left:auto; "
        f"text-align:right; max-width:45%;'>{e['detail']}</span>"
        f"</div>"
    )


def _events_column(heading: str, events: list[dict], links: list[dict], today: date) -> None:
    st.markdown(f"#### {heading}")
    if events:
        rows = "".join(_event_row(e, today) for e in events)
        st.markdown(f"<div class='panel' style='padding:0.3rem 0.4rem;'>{rows}</div>",
                    unsafe_allow_html=True)
    else:
        st.caption("No scheduled events in this window.")

    link_html = " · ".join(
        f"<a href='{l['url']}' target='_blank' style='color:{PALETTE['laser']}; "
        f"text-decoration:none;'>{l['label']} ↗</a>" for l in links
    )
    st.markdown(
        f"<div style='font-size:0.7rem; color:{PALETTE['haze']}; margin-top:0.4rem;'>"
        f"📅 Full calendar: {link_html}</div>",
        unsafe_allow_html=True,
    )


def render_market_events(symbols: list[str], days_ahead: int = 7) -> None:
    """
    Render upcoming market events, split India / International, each row linking
    to its source. Macro events (CPI/RBI/Fed) load on demand via NVIDIA NIM.
    """
    st.markdown(section_head(f"Market events · next {days_ahead} days"), unsafe_allow_html=True)

    data = _load_events(tuple(sorted(symbols)), days_ahead)
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()

    # Optional AI macro enrichment (button-triggered, cached 24h)
    if st.button("🤖 Add macro events (NVIDIA NIM · ~60s)", key="load_ai_macro",
                 help="CPI, central-bank meetings, GDP — extracted from live web "
                      "search by an NVIDIA NIM model. Cached for the day."):
        st.session_state["ai_macro_on"] = True

    india = list(data["india"])
    intl = list(data["international"])
    ai_note = ""
    if st.session_state.get("ai_macro_on"):
        with st.spinner("Fetching macro calendar via NVIDIA NIM…"):
            ai = _safe_ai_macro(days_ahead)
        if ai.get("ok"):
            india = sorted(india + ai["india"], key=lambda e: e["date"])
            intl = sorted(intl + ai["international"], key=lambda e: e["date"])
            ai_note = " · 🤖 macro events added"
        else:
            ai_note = (" · ⚠️ AI macro fetch didn't return in time — click again to "
                       "retry, or use the calendar links below")

    links = data["calendar_links"]
    col_in, col_intl = st.columns(2)
    with col_in:
        _events_column("🇮🇳 India", india, links["india"], today)
    with col_intl:
        _events_column("🌍 International", intl, links["international"], today)

    st.caption(
        "Earnings via Yahoo Finance · India holidays via Upstox · international "
        "holidays via exchange calendars · F&O expiry & NFP rule-derived · 🤖 macro "
        "events extracted by NVIDIA NIM from live search (verify via each link)."
        + ai_note
    )


__all__ = ["render_global_markets", "render_market_events"]
