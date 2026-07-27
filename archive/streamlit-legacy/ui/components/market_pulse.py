"""
ARTHA Terminal - Market Pulse hero
The landing-page header: live indices, a bull-vs-bear breadth bar driven by real
market internals, a sector-pulse strip, and an AI strategist's read.

Pure HTML/CSS (no CDN, no WebGL) so it always renders. Auto-refreshes every 60s;
the AI commentary is cached longer and only regenerates when internals shift.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from services.breadth import get_market_pulse, get_strategist_read
from ui.theme import PALETTE, clean_html
from ui.utils import format_change


_REFRESH = 20  # fragment cadence (visible refresh); indices Upstox live, breadth = 1 batched yf call
_PULSE_TTL = 13  # keep under _REFRESH so each fragment tick gets fresh data (avoids the 2× beat)
_READ_TTL = 600  # AI read cached 10 min


@st.cache_data(ttl=_PULSE_TTL, show_spinner=False)
def _load_pulse() -> dict:
    return get_market_pulse()


@st.cache_data(ttl=_READ_TTL, show_spinner=False)
def _load_read(_signature: str, _pulse: dict) -> dict:
    # _signature drives cache invalidation; _pulse is ignored for hashing.
    return get_strategist_read(_pulse)


def _fmt(v, dec=2):
    return f"{v:,.{dec}f}" if v is not None else "—"


def _index_tile(idx: dict) -> str:
    chg = idx.get("change")
    up = (chg or 0) >= 0
    color = PALETTE["surge"] if up else PALETTE["flare"]
    arrow = "▲" if up else "▼"
    chg_str = f"{arrow} {format_change(chg, price=idx.get('value'))}" if chg is not None else "—"
    rail = "card-up" if up else "card-down"
    dot = PALETTE["surge"] if idx.get("live") else PALETTE["haze"]
    return clean_html(f"""
    <div class="card {rail}" style="flex:1; min-width:150px;">
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <span style="font-size:0.68rem; letter-spacing:1.6px; font-weight:600;
                     color:{PALETTE['haze']}; text-transform:uppercase;">{idx['name']}</span>
        <span style="width:7px; height:7px; border-radius:50%; background:{dot};
                     box-shadow:0 0 8px {dot};"></span>
      </div>
      <div style="font-family:'JetBrains Mono'; font-size:1.85rem; font-weight:700;
                  letter-spacing:-0.5px; font-variant-numeric:tabular-nums;
                  color:{PALETTE['frost']}; margin:0.25rem 0 0.1rem;">{_fmt(idx['value'])}</div>
      <div style="font-family:'JetBrains Mono'; font-size:0.9rem; color:{color};
                  font-weight:600;">{chg_str}</div>
    </div>
    """)


def _breadth_bar(pulse: dict) -> str:
    b = pulse["breadth"]
    pct = b["pct"]
    mood = pulse["mood"]
    bull = PALETTE["surge"]
    bear = PALETTE["flare"]
    verdict = ("Bulls in control" if pct >= 55 else
               "Bears in control" if pct <= 45 else "Evenly matched")
    breadth_desc = ("broad-based" if pct >= 60 else "narrow" if pct <= 40 else "mixed")
    return clean_html(f"""
    <div style="margin:1.1rem 0 0.4rem;">
      <div style="display:flex; align-items:center; gap:0.6rem;">
        <span style="font-size:1.4rem;">🐂</span>
        <div style="flex:1; height:22px; border-radius:11px; overflow:hidden;
                    background:{bear}; border:1px solid {PALETTE['grid']}; position:relative;
                    box-shadow:inset 0 0 12px rgba(0,0,0,0.4);">
          <div style="width:{pct}%; height:100%;
                      background:linear-gradient(90deg,{bull},{bull}cc);
                      box-shadow:0 0 14px {bull}88;"></div>
          <div style="position:absolute; top:0; left:0; width:100%; height:100%;
                      display:flex; align-items:center; justify-content:center;
                      font-family:'JetBrains Mono'; font-size:0.72rem; font-weight:700;
                      color:{PALETTE['abyss']}; text-shadow:0 0 4px rgba(255,255,255,0.4);">
            {pct}% BULLISH
          </div>
        </div>
        <span style="font-size:1.4rem;">🐻</span>
      </div>
      <div style="text-align:center; font-size:0.78rem; color:{PALETTE['haze']}; margin-top:0.4rem;">
        <span style="color:{bull if pct>=50 else bear}; font-weight:700;">{verdict}</span>
        &nbsp;·&nbsp; {b['advancing']} of {b['total']} large-caps advancing — {breadth_desc}
        &nbsp;·&nbsp; <span style="font-weight:700;">{mood}</span>
      </div>
    </div>
    """)


def _sector_strip(pulse: dict) -> str:
    pills = []
    for s in pulse["sectors"]:
        up = s["avg_chg"] >= 0
        color = PALETTE["surge"] if up else PALETTE["flare"]
        arrow = "▲" if up else "▼"
        pills.append(
            f"<span style='display:inline-block; background:{color}18; color:{color}; "
            f"border:1px solid {color}44; border-radius:7px; padding:2px 9px; margin:3px; "
            f"font-family:JetBrains Mono; font-size:0.7rem;'>"
            f"{s['sector']} {arrow}{abs(s['avg_chg']):.1f}%</span>"
        )
    return (
        f"<div style='margin-top:0.4rem;'>"
        f"<span style='font-size:0.64rem; color:{PALETTE['haze']}; text-transform:uppercase; "
        f"letter-spacing:1.5px;'>Sector pulse</span><br>{''.join(pills)}</div>"
    )


def _strategist_block(read: dict, when: datetime) -> str:
    tag = "AI · NIM" if read.get("ai") else "computed summary"
    return clean_html(f"""
    <div class="card" style="margin-top:0.9rem;
                border-left:3px solid {PALETTE['laser']};">
      <div style="display:flex; justify-content:space-between; align-items:center;
                  margin-bottom:0.35rem;">
        <span style="color:{PALETTE['laser']}; font-weight:700; font-size:0.72rem;
                     letter-spacing:1.4px; text-transform:uppercase;">Strategist's read</span>
        <span style="color:{PALETTE['haze']}; font-size:0.62rem;">{tag} · {when:%H:%M IST}</span>
      </div>
      <div style="color:{PALETTE['frost']}; font-size:0.86rem; line-height:1.55;">
        {read['text']}
      </div>
    </div>
    """)


@st.fragment(run_every=_REFRESH)
def render_market_pulse() -> None:
    """Render the auto-refreshing Market Pulse hero."""
    pulse = _load_pulse()
    gen = datetime.fromisoformat(pulse["generated_ist"])
    sig = f"{pulse['breadth']['pct']}-{pulse['mood_key']}"
    read = _load_read(sig, pulse)

    # Masthead — left-aligned bar, not a centered splash with air around it
    st.markdown(
        clean_html(f"""
        <div style="display:flex; align-items:center; justify-content:space-between;
                    gap:1rem; padding-bottom:0.9rem; margin-bottom:1rem;
                    border-bottom:1px solid var(--border);">
          <div style="display:flex; align-items:baseline; gap:0.85rem;">
            <span style="font-size:1.7rem; font-weight:700; letter-spacing:-0.5px;
                         background:linear-gradient(100deg,{PALETTE['frost']} 10%,{PALETTE['laser']} 90%);
                         -webkit-background-clip:text; -webkit-text-fill-color:transparent;
                         background-clip:text;">ARTHA Terminal</span>
            <span style="color:{PALETTE['haze']}; font-size:0.74rem; letter-spacing:1.5px;
                         text-transform:uppercase;">Indian equities · AI market pulse</span>
          </div>
          <span style="display:inline-flex; align-items:center; gap:6px; flex-shrink:0;
                       background:rgba(52,211,153,0.12); border:1px solid rgba(52,211,153,0.45);
                       color:{PALETTE['surge']}; border-radius:999px; padding:3px 11px;
                       font-size:0.66rem; font-weight:700; letter-spacing:1.2px;">
            <span style="width:6px; height:6px; border-radius:50%;
                         background:{PALETTE['surge']}; box-shadow:0 0 8px {PALETTE['surge']};"></span>
            LIVE
          </span>
        </div>
        """),
        unsafe_allow_html=True,
    )

    # Index tiles
    tiles = "".join(_index_tile(i) for i in pulse["indices"])
    st.markdown(
        f"<div style='display:flex; gap:1rem; flex-wrap:wrap; margin-top:0.8rem;'>{tiles}</div>",
        unsafe_allow_html=True,
    )

    # Breadth bar + sector strip + strategist read
    st.markdown(_breadth_bar(pulse), unsafe_allow_html=True)
    if pulse["sectors"]:
        st.markdown(_sector_strip(pulse), unsafe_allow_html=True)
    st.markdown(_strategist_block(read, gen), unsafe_allow_html=True)

    st.markdown(
        f"<div style='text-align:right; font-size:0.62rem; color:{PALETTE['haze']}; "
        f"margin-top:0.3rem;'>⟳ auto-refresh {_REFRESH}s · breadth from {pulse['universe']} "
        f"{pulse.get('universe_label', 'stocks')} · updated {gen:%H:%M:%S IST}</div>",
        unsafe_allow_html=True,
    )


__all__ = ["render_market_pulse"]
