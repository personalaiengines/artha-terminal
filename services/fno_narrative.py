"""
ARTHA Terminal - F&O narrative (grounded)

Takes the deterministic F&O game plan (services.fno_analysis) and asks the
configured OpenRouter model (config.ai.primary_model — a free-tier model by
default) to write a senior-derivatives-analyst read. The model is given ONLY
the computed numbers and told not to invent anything — the maths is done in
Python, the LLM only interprets. Educational/SEBI-safe, never a buy/sell call.
Falls back to the OpenRouter fallback model, then NVIDIA NIM, if the primary
model is unavailable.
"""

from __future__ import annotations

import re
import httpx
from config import config

_SYSTEM = (
    "You are a rigorous, grounded senior F&O/derivatives strategist for Indian "
    "index options. You never fabricate numbers and never give direct buy/sell "
    "advice — you explain what the option-chain structure implies, educationally."
)


def _fmt(v, suffix=""):
    if v is None:
        return "n/a"
    try:
        return f"{float(v):,.2f}{suffix}"
    except Exception:
        return f"{v}{suffix}"


def _facts_block(plan: dict) -> str:
    """Compact, factual context from the deterministic plan (no invented data)."""
    b = plan.get("bias", {}) or {}
    em = plan.get("expected_move") or {}
    walls = plan.get("oi_walls") or {}
    strat = plan.get("strategy") or {}
    drivers = "; ".join(
        f"{d['name']} {d['detail']} ({d['delta']:+})" for d in b.get("drivers", [])
    )
    levels = "; ".join(f"{l['label']} {l['price']:g}" for l in plan.get("levels", []))

    em_line = (
        f"Expected move to expiry: ±{_fmt(em.get('straddle'))} "
        f"({_fmt(em.get('pct'), '%')}) → band {_fmt(em.get('lower'))}–{_fmt(em.get('upper'))}"
        if em else "Expected move: n/a"
    )
    return "\n".join([
        f"Index: {plan.get('name')} | Spot: {_fmt(plan.get('spot'))} | "
        f"ATM: {_fmt(plan.get('atm'))} | Expiry: {plan.get('expiry')}",
        f"Bias (deterministic, options-flow): {b.get('label')} "
        f"(score {b.get('score')}/100) | drivers: {drivers or 'n/a'}",
        f"PCR (OI): {_fmt(plan.get('pcr_oi'))} | Max pain: {_fmt(plan.get('max_pain'))}",
        f"OI walls — Call/resistance: {_fmt(walls.get('call_wall'))} | "
        f"Put/support: {_fmt(walls.get('put_wall'))}",
        f"ATM IV: {_fmt(plan.get('atm_iv'), '%')} | India VIX: {_fmt(plan.get('india_vix'))}",
        em_line,
        f"Strategy concept: {strat.get('name')} (IV regime {strat.get('iv_regime')}) — "
        f"{strat.get('note')}",
        f"Key levels: {levels}",
    ])


def _build_prompt(plan: dict) -> str:
    facts = _facts_block(plan)
    return (
        f"Using ONLY the verified figures below for {plan.get('name')} index options, "
        f"write a concise senior-strategist read. Do NOT invent any number or level "
        f"not present here; if something is 'n/a', acknowledge the gap.\n\n"
        f"=== VERIFIED DATA ===\n{facts}\n=====================\n\n"
        f"Write in Markdown with these exact sections:\n"
        f"### Market Structure\n(2-3 sentences: where spot sits vs max pain, the OI walls, "
        f"and the bias — cite the figures)\n"
        f"### Options Positioning\n(3-4 bullets reading PCR, OI walls and max pain — what "
        f"writers are defending, each citing a number)\n"
        f"### Volatility & Range\n(2-3 sentences on ATM IV / India VIX and the expected-move "
        f"band; what a move to either edge would mean)\n"
        f"### How the Levels Trade\n(2-3 bullets on the key support/resistance levels and how "
        f"price interacts with them intraday)\n"
        f"### Strategist View\n(a cautious, educational leaning consistent with the bias and "
        f"IV regime — NOT a buy/sell recommendation)\n\n"
        f"Keep it tight and specific. Educational content under SEBI norms, not advice."
    )


def _openrouter(model: str, prompt: str, timeout: float, max_tokens: int = 700) -> str:
    key = config.ai.openrouter_api_key
    if not key:
        return ""

    def _call(mt: int):
        return httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {key}",
                "HTTP-Referer": "https://artha.local",
                "X-Title": "ARTHA Terminal",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": mt, "temperature": 0.3,
            },
            timeout=timeout,
        )

    try:
        r = _call(max_tokens)
        # Free-tier rate/credit ceiling → 402 "can only afford N tokens".
        # Retry within budget instead of dropping straight to the next model.
        if r.status_code == 402:
            m = re.search(r"can only afford (\d+)", r.text)
            afford = int(m.group(1)) - 24 if m else 0
            if afford >= 200:
                r = _call(afford)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"]
    except Exception:
        return ""
    return ""


def _nim(model: str, prompt: str, timeout: float) -> str:
    key = config.ai.nvidia_api_key
    if not key:
        return ""
    try:
        r = httpx.post(
            "https://integrate.api.nvidia.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 1000, "temperature": 0.3,
            },
            timeout=timeout,
        )
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"]
    except Exception:
        return ""
    return ""


def get_fno_narrative(plan: dict) -> dict:
    """
    Grounded senior-analyst narrative for one index's game plan.

    config.ai.primary_model (OpenRouter, free-tier) first, then the OpenRouter
    fallback model, then NVIDIA NIM. Returns {"markdown", "ok", "model"}.
    """
    if not plan or not plan.get("ok"):
        return {"markdown": "", "ok": False, "model": None}

    prompt = _build_prompt(plan)

    # Primary OpenRouter model first — retried, since free-tier endpoints
    # occasionally reset the connection under load; only then fall back so the
    # primary model is genuinely used, not skipped on a transient blip. Then
    # the OpenRouter fallback model, then NVIDIA NIM.
    attempts = [
        (_openrouter, config.ai.primary_model, 90.0, 3),
        (_openrouter, config.ai.fallback_model_1, 60.0, 1),
        (_nim, "meta/llama-3.3-70b-instruct", 90.0, 1),
    ]
    for fn, model, timeout, tries in attempts:
        for _ in range(tries):
            text = fn(model, prompt, timeout)
            if text and len(text) > 120:
                return {"markdown": _clean(text), "ok": True, "model": model}
    return {"markdown": "", "ok": False, "model": None}


def _clean(text: str) -> str:
    """Some reasoning-style models (e.g. Nemotron) prepend their own scratchpad
    /instruction-echo before the actual answer. The required format always
    starts at the first '### ' heading — drop anything before it."""
    i = text.find("### ")
    return text[i:].strip() if i > 0 else text.strip()


__all__ = ["get_fno_narrative"]
