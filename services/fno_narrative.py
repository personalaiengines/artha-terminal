"""
ARTHA Terminal - F&O narrative (grounded)

Takes the deterministic F&O game plan (services.fno_analysis) and asks the LLM
to write a senior-derivatives-analyst read. The model is given ONLY the
computed numbers and told not to invent anything — the maths is done in Python,
the LLM only interprets. Educational/SEBI-safe, never a buy/sell call.

Runs on agent.llm_client's "deep" tier chain, so provider fallback and
rate-limit cooldowns are handled in one place rather than here.
"""

from __future__ import annotations


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


def get_fno_narrative(plan: dict) -> dict:
    """
    Grounded senior-analyst narrative for one index's game plan.

    Runs on the router's "deep" chain. This used to hand-roll its own ladder —
    OpenRouter primary x3, OpenRouter fallback, then one NIM model — which the
    router already does, plus GitHub Models and SambaNova, plus cooldowns for
    tiers that have started 429ing. Returns {"markdown", "ok", "model"}.
    """
    from agent.llm_client import complete

    if not plan or not plan.get("ok"):
        return {"markdown": "", "ok": False, "model": None}

    text = complete(_SYSTEM, _build_prompt(plan), task_shape="deep")
    if text and len(text) > 120:
        return {"markdown": _clean(text), "ok": True, "model": "router"}
    return {"markdown": "", "ok": False, "model": None}


def _clean(text: str) -> str:
    """Some reasoning-style models (e.g. Nemotron) prepend their own scratchpad
    /instruction-echo before the actual answer. The required format always
    starts at the first '### ' heading — drop anything before it."""
    i = text.find("### ")
    return text[i:].strip() if i > 0 else text.strip()


__all__ = ["get_fno_narrative"]
