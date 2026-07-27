"""
ARTHA Terminal - Upstox token status + regeneration UI

Surfaces the daily portfolio access-token state and gives a near-one-click
regenerate flow (Upstox mandates a daily interactive login — there is no
headless refresh). Also auto-captures the OAuth code if Upstox redirects back
to the app with ?code=... in the URL.
"""

import streamlit as st

from services.upstox_auth import (
    authorize_url, check_access_token, exchange_code, token_saved_at,
)
from ui.theme import PALETTE, clean_html


@st.cache_data(ttl=120, show_spinner=False)
def _status() -> dict:
    return check_access_token()


_STATUS_STYLE = {
    "ok": (PALETTE["surge"], "🟢 Portfolio token active"),
    "expired": (PALETTE["flare"], "🔴 Portfolio token expired"),
    "missing": (PALETTE["volt"], "⚠️ Portfolio token not set"),
    "error": (PALETTE["haze"], "⚪ Token status unknown"),
}


def _auto_capture() -> str | None:
    """If Upstox redirected back with ?code=..., exchange it automatically."""
    try:
        code = st.query_params.get("code")
    except Exception:
        code = None
    if not code:
        return None
    res = exchange_code(code)
    try:
        del st.query_params["code"]   # clean the URL so it isn't re-used
    except Exception:
        pass
    if res.get("ok"):
        _status.clear()
    return res.get("message")


def _regenerate_flow() -> None:
    """The login-link + paste-code regenerate steps."""
    st.markdown(
        f"<div style='font-size:0.8rem; color:{PALETTE['haze']};'>"
        f"Upstox issues a fresh token only after an interactive login "
        f"(no headless refresh). Two quick steps:</div>",
        unsafe_allow_html=True,
    )
    st.link_button("🔐 Step 1 · Log in to Upstox", authorize_url())
    st.caption(
        "After you approve, Upstox redirects back with a `code`. If it lands on "
        "this app the token is captured automatically; otherwise copy the redirect "
        "URL (or just the code) and paste it below."
    )
    with st.form("upstox_regen", clear_on_submit=True):
        pasted = st.text_input(
            "Step 2 · Paste the redirect URL or code",
            placeholder="http://localhost:8501/?code=...  or  the raw code",
            label_visibility="visible",
        )
        submitted = st.form_submit_button("Regenerate token")
    if submitted and pasted:
        res = exchange_code(pasted)
        if res.get("ok"):
            _status.clear()
            st.success(res["message"])
            st.rerun()
        else:
            st.error(res["message"])


def render_token_status(show_regenerate: bool = True) -> None:
    """Full token-status panel with the regenerate flow (portfolio page)."""
    auto_msg = _auto_capture()
    if auto_msg:
        st.toast(auto_msg)

    status = _status()
    color, label = _STATUS_STYLE.get(status["status"], _STATUS_STYLE["error"])
    saved = token_saved_at()
    saved_line = (f" · last regenerated {saved[:16].replace('T', ' ')} IST"
                  if saved else "")

    st.markdown(
        clean_html(f"""
        <div class="panel" style="padding:0.8rem 1rem; border-left:3px solid {color};">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <span style="color:{color}; font-weight:700;">{label}</span>
            <span style="color:{PALETTE['haze']}; font-size:0.7rem;">
              {status.get('name') or ''}{saved_line}</span>
          </div>
          <div style="color:{PALETTE['haze']}; font-size:0.76rem; margin-top:0.2rem;">
            {status['message']}
          </div>
        </div>
        """),
        unsafe_allow_html=True,
    )

    if show_regenerate and status["status"] in ("expired", "missing", "error"):
        with st.expander("🔄 Regenerate Upstox access token", expanded=status["status"] != "ok"):
            _regenerate_flow()


def render_token_banner() -> None:
    """Compact banner for the landing page — only shows when action is needed."""
    _auto_capture()
    status = _status()
    if status["status"] == "ok":
        return
    color, label = _STATUS_STYLE.get(status["status"], _STATUS_STYLE["error"])
    st.markdown(
        clean_html(f"""
        <div style="background:{color}14; border:1px solid {color}55; border-radius:10px;
                    padding:0.55rem 0.9rem; margin:0.4rem 0; display:flex;
                    justify-content:space-between; align-items:center;">
          <span style="color:{color}; font-size:0.82rem; font-weight:600;">{label}</span>
          <a href="{authorize_url()}" target="_blank" style="color:{PALETTE['laser']};
             font-size:0.78rem; text-decoration:none; font-weight:600;">
             Regenerate ↗</a>
        </div>
        """),
        unsafe_allow_html=True,
    )
    st.caption("Open **My Portfolio** to paste the code and finish regenerating.")


__all__ = ["render_token_status", "render_token_banner"]
