"""
ARTHA Terminal - Institutional Flows (FII/DII) panel
Real daily FII/DII net cash flows from NSE + accumulated trend, plus an optional
AI "flow intelligence" read (news-derived, sourced) on where they're active.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from services.institutional_flows import get_institutional_snapshot, get_flow_intelligence
from ui.theme import PALETTE, clean_html, section_head


_TTL = 30 * 60      # NSE publishes once/day — 30 min cache is plenty
_INTEL_TTL = 6 * 3600


@st.cache_data(ttl=_TTL, show_spinner=False)
def _load_snapshot() -> dict:
    snap = get_institutional_snapshot()
    # Don't let an empty (all-failed) result stick in cache for the full TTL —
    # raising here prevents caching so the next render retries the NSE source.
    if not snap.get("fii") and not snap.get("dii"):
        raise RuntimeError("no FII/DII data")
    return snap


def _safe_snapshot() -> dict:
    try:
        return _load_snapshot()
    except Exception:
        return {}


@st.cache_data(ttl=_INTEL_TTL, show_spinner="Reading institutional flow news…")
def _load_intel() -> dict:
    # Cache only on success — a failed NIM/search attempt must not stick for 6h.
    r = get_flow_intelligence()
    if not r.get("ok"):
        raise RuntimeError("flow intelligence fetch failed")
    return r


def _safe_intel() -> dict:
    try:
        return _load_intel()
    except Exception:
        return {"items": [], "ok": False}


def _flow_card(title: str, rec: dict, stance: str, key: str) -> str:
    color = PALETTE["surge"] if key == "bullish" else (
        PALETTE["flare"] if key == "bearish" else PALETTE["haze"])
    if not rec:
        return clean_html(f"""
        <div class="card" style="flex:1;">
          <div style="color:{PALETTE['haze']}; font-size:0.7rem; letter-spacing:1.6px;
                      font-weight:600; text-transform:uppercase;">{title}</div>
          <div style="color:{PALETTE['haze']}; margin-top:0.5rem;">data unavailable</div>
        </div>""")
    net = rec["net"]
    sign = "+" if net >= 0 else ""
    return clean_html(f"""
    <div class="card" style="flex:1; min-width:210px; border-left:3px solid {color};">
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <span style="color:{PALETTE['haze']}; font-weight:600; font-size:0.7rem;
                     letter-spacing:1.6px; text-transform:uppercase;">{title}</span>
        <span style="color:{color}; font-size:0.68rem; font-weight:700;">{stance}</span>
      </div>
      <div style="font-family:'JetBrains Mono'; font-size:1.85rem; font-weight:700;
                  letter-spacing:-0.5px; font-variant-numeric:tabular-nums;
                  color:{color}; margin:0.3rem 0 0.15rem;">{sign}₹{net:,.0f} Cr</div>
      <div style="font-size:0.72rem; color:{PALETTE['haze']}; font-family:'JetBrains Mono';">
        Buy ₹{rec['buy']:,.0f} Cr &nbsp;·&nbsp; Sell ₹{rec['sell']:,.0f} Cr
      </div>
    </div>
    """)


def _trend_strip(trend: dict) -> str:
    series = trend.get("series", [])
    if not series:
        return ""
    bars = []
    peak = max((abs(r["fii_net"]) for r in series), default=1) or 1
    for r in series:
        v = r["fii_net"]
        color = PALETTE["surge"] if v >= 0 else PALETTE["flare"]
        h = max(4, int(abs(v) / peak * 28))
        bars.append(
            f"<span title='{r['date']}: FII {v:+,.0f} Cr' style='display:inline-block; "
            f"width:9px; height:{h}px; background:{color}; margin:0 2px; border-radius:2px; "
            f"vertical-align:bottom;'></span>"
        )
    fs, ds = trend.get("fii_streak", 0), trend.get("dii_streak", 0)

    def _streak_txt(n, who):
        if n == 0:
            return ""
        word = "buying" if n > 0 else "selling"
        col = PALETTE["surge"] if n > 0 else PALETTE["flare"]
        return (f"<span style='color:{col};'>{who} {abs(n)}d net {word}</span>")

    label = " · ".join(x for x in [_streak_txt(fs, "FII"), _streak_txt(ds, "DII")] if x)
    return (
        f"<div style='margin-top:0.6rem;'>"
        f"<span style='font-size:0.64rem; color:{PALETTE['haze']}; text-transform:uppercase; "
        f"letter-spacing:1.5px;'>FII net-flow trend ({len(series)}d)</span><br>"
        f"<span style='display:inline-block; padding:4px 0;'>{''.join(bars)}</span>"
        f"&nbsp;&nbsp;<span style='font-size:0.72rem;'>{label}</span></div>"
    )


def render_institutional_flows() -> None:
    """Render the FII/DII flows panel with optional AI flow intelligence."""
    st.markdown(section_head("Institutional flows · FII / DII"), unsafe_allow_html=True)

    snap = _safe_snapshot()
    if not snap.get("fii") and not snap.get("dii"):
        st.info("FII/DII data is temporarily unavailable (NSE source). It will "
                "refresh automatically — NSE publishes the figure after market close.")
        return

    stale_note = (" · <span style='color:" + PALETTE["volt"] + ";'>last available</span>"
                  if snap.get("stale") else "")
    st.markdown(
        f"<div style='font-size:0.72rem; color:{PALETTE['haze']}; margin-bottom:0.5rem;'>"
        f"NSE cash-market provisional · <span style='color:{PALETTE['volt']};'>"
        f"{snap.get('date','—')}</span>{stale_note}</div>",
        unsafe_allow_html=True,
    )

    cards = (_flow_card("FII / FPI", snap.get("fii"), snap["fii_stance"], snap["fii_key"])
             + _flow_card("DII", snap.get("dii"), snap["dii_stance"], snap["dii_key"]))
    st.markdown(
        f"<div style='display:flex; gap:1rem; flex-wrap:wrap;'>{cards}</div>",
        unsafe_allow_html=True,
    )

    trend_html = _trend_strip(snap.get("trend", {}))
    if trend_html:
        st.markdown(trend_html, unsafe_allow_html=True)
    if len(snap.get("trend", {}).get("series", [])) < 2:
        st.caption("Trend builds up as daily readings accumulate (NSE publishes one figure per day).")

    # AI flow intelligence (button-triggered — slow news+LLM call)
    if st.button("Where are FIIs/DIIs active? (AI · news-derived)", key="flow_intel",
                 icon=":material/neurology:",
                 help="Summarises recent news on FII/DII sector & stock activity via "
                      "NVIDIA NIM, with source links. Not official flow data."):
        st.session_state["flow_intel_on"] = True

    if st.session_state.get("flow_intel_on"):
        intel = _safe_intel()
        if intel.get("ok"):
            rows = []
            for it in intel["items"]:
                col = PALETTE["surge"] if it["direction"] == "buying" else PALETTE["flare"]
                who_col = PALETTE["laser"] if it["who"] == "FII" else PALETTE["volt"]
                rows.append(
                    f"<div style='display:flex; align-items:center; gap:0.6rem; padding:0.4rem 0.6rem; "
                    f"border-bottom:1px solid {PALETTE['grid']}44;'>"
                    f"<span style='color:{who_col}; font-weight:700; font-size:0.72rem; "
                    f"min-width:34px;'>{it['who']}</span>"
                    f"<span style='color:{col}; font-size:0.72rem; text-transform:uppercase; "
                    f"min-width:56px;'>{it['direction']}</span>"
                    f"<a href='{it['source_url']}' target='_blank' style='color:{PALETTE['frost']}; "
                    f"text-decoration:none; font-weight:600; border-bottom:1px dotted {PALETTE['haze']};'>"
                    f"{it['target']} ↗</a>"
                    f"<span style='color:{PALETTE['haze']}; font-size:0.68rem; margin-left:auto; "
                    f"text-align:right; max-width:45%;'>{it['note']}</span></div>"
                )
            st.markdown(
                f"<div class='panel' style='padding:0.3rem 0.5rem; margin-top:0.5rem;'>{''.join(rows)}</div>",
                unsafe_allow_html=True,
            )
            st.caption(
                "⚠️ News-derived market commentary summarised by NVIDIA NIM — NOT official "
                "flow data. FII/DII stock-level activity is only officially disclosed quarterly. "
                "Verify each claim via its source link."
            )
        else:
            st.warning("The AI read didn't return in time (NIM's free tier is "
                       "variable). Click the button again to retry.")


__all__ = ["render_institutional_flows"]
