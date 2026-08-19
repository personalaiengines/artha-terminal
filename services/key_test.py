"""
ARTHA Terminal - live credential verification

One question, answered honestly: does THIS key, right now, actually work
against its real provider? Used by the registration wizard and Settings before
a key is ever stored, so a typo fails on the screen where it was typed rather
than three screens (or three weeks) later as a mysteriously empty panel.

Deliberately bypasses every service class in this repo (UpstoxClient,
SearchService, the LLMClient hierarchy) — all of them read their key from
`config` at construction, bound to whatever the CURRENT request's user
resolves to. Testing a key someone just pasted and has not saved yet needs a
key with no user behind it at all, so this module speaks to each provider
directly over httpx instead of borrowing config-bound plumbing.

Every function returns {"ok": bool, "detail": str} and never raises — a
malformed key, a timeout, or a provider outage all become `ok: False` with a
plain-English `detail`, not a 500.
"""

from __future__ import annotations

import time

import httpx

_TIMEOUT = 15.0


# ----------------------------------------------------------------------
# LLM providers — one minimal chat completion each. All four speak the same
# OpenAI-shaped /chat/completions wire format (agent/llm_client.py already
# relies on this), so one body shape covers Groq, Google, OpenRouter and NIM.
# ----------------------------------------------------------------------

_LLM_ENDPOINTS = {
    "GROQ_API_KEY": ("https://api.groq.com/openai/v1/chat/completions", "openai/gpt-oss-120b", None),
    "GOOGLE_API_KEY": ("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
                       "gemini-flash-lite-latest", None),
    "OPENROUTER_API_KEY": ("https://openrouter.ai/api/v1/chat/completions",
                           "nvidia/nemotron-3-super-120b-a12b:free",
                           {"HTTP-Referer": "https://artha.local", "X-Title": "ARTHA Terminal"}),
    "NVIDIA_API_KEY": ("https://integrate.api.nvidia.com/v1/chat/completions",
                       "mistralai/mistral-nemotron", None),
    "SAMBANOVA_API_KEY": ("https://api.sambanova.ai/v1/chat/completions",
                          "Meta-Llama-3.3-70B-Instruct", None),
    "GITHUB_MODELS_TOKEN": ("https://models.inference.ai.azure.com/chat/completions",
                            "Llama-3.3-70B-Instruct", None),
}


async def _test_openai_shaped(url: str, key: str, model: str, extra_headers: dict | None) -> dict:
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if extra_headers:
        headers |= extra_headers
    payload = {"model": model, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 4}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        t0 = time.monotonic()
        r = await client.post(url, headers=headers, json=payload)
        elapsed = time.monotonic() - t0
    if r.status_code == 200:
        return {"ok": True, "detail": f"Verified · {model} answered in {elapsed:.2f}s"}
    if r.status_code in (401, 403):
        return {"ok": False, "detail": "Rejected — the key is invalid or lacks access"}
    if r.status_code == 429:
        return {"ok": False, "detail": "The key is valid, but its free quota is exhausted right now"}
    return {"ok": False, "detail": f"Provider returned HTTP {r.status_code}"}


async def _test_anthropic(key: str) -> dict:
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    payload = {"model": "claude-haiku-4-5-20251001", "max_tokens": 4,
               "messages": [{"role": "user", "content": "hi"}]}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        t0 = time.monotonic()
        r = await client.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload)
        elapsed = time.monotonic() - t0
    if r.status_code == 200:
        return {"ok": True, "detail": f"Verified · answered in {elapsed:.2f}s (this is a PAID key)"}
    if r.status_code in (401, 403):
        return {"ok": False, "detail": "Rejected — the key is invalid"}
    return {"ok": False, "detail": f"Provider returned HTTP {r.status_code}"}


# ----------------------------------------------------------------------
# Everything else
# ----------------------------------------------------------------------

async def _test_upstox_analytics(token: str) -> dict:
    """The cheapest authenticated Upstox call that proves the token actually
    works: the market-holidays list. No symbol, no date range, same route
    services/upstox.py:504 already treats as the authoritative holiday source."""
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.get("https://api.upstox.com/v2/market/holidays", headers=headers)
    if r.status_code == 200:
        n = len(r.json().get("data") or [])
        return {"ok": True, "detail": f"Verified · token valid, {n} holidays returned"}
    if r.status_code in (401, 403):
        return {"ok": False, "detail": "Rejected — the analytics token is invalid or expired"}
    return {"ok": False, "detail": f"Upstox returned HTTP {r.status_code}"}


async def _test_finnhub(key: str) -> dict:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.get("https://finnhub.io/api/v1/quote",
                             params={"symbol": "AAPL", "token": key})
    if r.status_code == 200 and "c" in (r.json() or {}):
        return {"ok": True, "detail": "Verified · quote endpoint answered"}
    if r.status_code in (401, 403):
        return {"ok": False, "detail": "Rejected — the key is invalid"}
    return {"ok": False, "detail": f"Finnhub returned HTTP {r.status_code}"}


async def _test_serpapi(key: str) -> dict:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.get("https://serpapi.com/account", params={"api_key": key})
    if r.status_code == 200:
        left = (r.json() or {}).get("plan_searches_left")
        return {"ok": True, "detail": f"Verified · {left} searches left this month"
                                       if left is not None else "Verified"}
    if r.status_code in (401, 403):
        return {"ok": False, "detail": "Rejected — the key is invalid"}
    return {"ok": False, "detail": f"SerpAPI returned HTTP {r.status_code}"}


async def _test_jina(key: str) -> dict:
    headers = {"Authorization": f"Bearer {key}"}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.get("https://r.jina.ai/https://example.com", headers=headers)
    if r.status_code == 200:
        return {"ok": True, "detail": "Verified · reader endpoint answered"}
    if r.status_code in (401, 403):
        return {"ok": False, "detail": "Rejected — the key is invalid"}
    return {"ok": False, "detail": f"Jina returned HTTP {r.status_code}"}


# Providers with no live check worth making: OAuth client credentials
# (validated only by completing the actual OAuth dance, not a single call),
# and a self-hosted search URL (a reachability ping proves the box answers,
# not that it is correctly configured — not worth the false confidence).
_UNTESTABLE = {
    "UPSTOX_CLIENT_ID", "UPSTOX_CLIENT_SECRET", "UPSTOX_ACCESS_TOKEN",
    "UPSTOX_REDIRECT_URI", "SEARXNG_URL", "SERPER_API_KEY", "BING_API_KEY",
}


async def test_key(provider: str, value: str) -> dict:
    """provider: an env-var name from api.server._KNOWN_KEY_PROVIDERS.
    Never raises — every branch below is wrapped or already exception-shaped."""
    value = (value or "").strip()
    if not value:
        return {"ok": False, "detail": "Enter a key first"}

    try:
        if provider in _LLM_ENDPOINTS:
            url, model, extra = _LLM_ENDPOINTS[provider]
            return await _test_openai_shaped(url, value, model, extra)
        if provider == "ANTHROPIC_API_KEY":
            return await _test_anthropic(value)
        if provider == "UPSTOX_ANALYTICS_TOKEN":
            return await _test_upstox_analytics(value)
        if provider == "FINNHUB_API_KEY":
            return await _test_finnhub(value)
        if provider == "SERPAPI_KEY":
            return await _test_serpapi(value)
        if provider == "JINA_API_KEY":
            return await _test_jina(value)
        if provider in _UNTESTABLE:
            return {"ok": True, "detail": "Saved — this credential has no live check, "
                                          "so it is trusted rather than verified"}
        return {"ok": False, "detail": f"Unrecognised provider: {provider}"}
    except httpx.TimeoutException:
        return {"ok": False, "detail": "The provider did not respond in time"}
    except Exception as e:
        return {"ok": False, "detail": f"Could not reach the provider ({type(e).__name__})"}


__all__ = ["test_key"]
