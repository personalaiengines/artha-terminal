"""
ARTHA Terminal - Upstox access-token lifecycle

The Upstox *access token* (portfolio/holdings) expires daily (~03:30 IST) and
Upstox provides NO refresh token — their OAuth mandates an interactive login
each day, so fully headless renewal is impossible. What we automate:

  • check_access_token()  — is the current token valid, expired, or missing?
  • authorize_url()       — the Upstox login URL (user logs in → gets a code)
  • exchange_code(code)   — swap that code for a fresh access token
  • save_access_token()   — persist it (survives restarts / Docker volume)

So regeneration is one login + one paste (or an automatic redirect capture),
which is as close to one-click as Upstox permits.
"""

from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from config import config

_TOKEN_URL = "https://api.upstox.com/v2/login/authorization/token"
_PROFILE_URL = "https://api.upstox.com/v2/user/profile"


def authorize_url() -> str:
    return config.upstox.authorize_url()


def check_access_token() -> dict:
    """
    Validate the portfolio access token with a cheap authenticated call.

    Returns {"status": "ok"|"expired"|"missing"|"error", "message": str,
             "name": str|None}.
    """
    token = config.upstox.access_token
    if not token:
        return {"status": "missing", "message": "No access token configured.", "name": None}
    try:
        r = httpx.get(
            _PROFILE_URL,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=12.0,
        )
    except Exception as e:
        return {"status": "error", "message": str(e)[:120], "name": None}

    if r.status_code == 200:
        data = r.json().get("data", {}) or {}
        return {"status": "ok", "message": "Token valid.",
                "name": data.get("user_name") or data.get("email")}
    if r.status_code == 401:
        return {"status": "expired",
                "message": "Access token expired — regenerate via Upstox login.", "name": None}
    return {"status": "error", "message": f"HTTP {r.status_code}", "name": None}


def exchange_code(code: str) -> dict:
    """
    Exchange an OAuth authorization code for a fresh access token and persist it.

    Returns {"ok": bool, "message": str}.
    """
    code = (code or "").strip()
    # Accept a full redirect URL and pull ?code=... out of it.
    if "code=" in code:
        from urllib.parse import urlparse, parse_qs
        try:
            qs = parse_qs(urlparse(code).query)
            code = (qs.get("code") or [code])[0]
        except Exception:
            pass
    if not code:
        return {"ok": False, "message": "No authorization code provided."}

    up = config.upstox
    if not (up.client_id and up.client_secret):
        return {"ok": False, "message": "UPSTOX_CLIENT_ID / SECRET not configured."}

    try:
        r = httpx.post(
            _TOKEN_URL,
            headers={"Accept": "application/json",
                     "Content-Type": "application/x-www-form-urlencoded"},
            data={
                "code": code,
                "client_id": up.client_id,
                "client_secret": up.client_secret,
                "redirect_uri": up.redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=20.0,
        )
    except Exception as e:
        return {"ok": False, "message": f"Token request failed: {str(e)[:120]}"}

    if r.status_code != 200:
        # Upstox returns a helpful error body (e.g. redirect_uri mismatch).
        try:
            err = r.json()
        except Exception:
            err = r.text[:160]
        return {"ok": False, "message": f"Upstox rejected the code: {err}"}

    token = r.json().get("access_token")
    if not token:
        return {"ok": False, "message": "No access_token in Upstox response."}

    save_access_token(token)
    return {"ok": True, "message": "Access token regenerated and saved."}


def save_access_token(token: str) -> None:
    """Persist the token to the volume-backed file and update the live config."""
    try:
        config.upstox_token_file.parent.mkdir(parents=True, exist_ok=True)
        config.upstox_token_file.write_text(
            json.dumps({
                "access_token": token,
                "saved_at": datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(),
            }),
            encoding="utf-8",
        )
    except Exception:
        pass
    config.upstox.access_token = token  # take effect immediately


def token_saved_at() -> str | None:
    """When the persisted token was last saved (ISO IST), if any."""
    try:
        if config.upstox_token_file.exists():
            return json.loads(config.upstox_token_file.read_text(encoding="utf-8")).get("saved_at")
    except Exception:
        pass
    return None


__all__ = ["authorize_url", "check_access_token", "exchange_code",
           "save_access_token", "token_saved_at"]
