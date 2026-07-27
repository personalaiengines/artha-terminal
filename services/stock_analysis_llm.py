"""
ARTHA Terminal - LLM stock analysis (grounded, works for any stock)

Takes the live yfinance/Upstox snapshot (services.stock_data) and asks an NVIDIA
NIM model to write a senior-analyst read. The model is given ONLY the computed
numbers and told not to invent anything — the maths is done in Python, the LLM
only interprets. Output is educational framing (SEBI-safe), never buy/sell advice.

Open-source / free tier: NVIDIA NIM. Falls back gracefully if unavailable.
"""

from __future__ import annotations

from config import config

# Larger NIM model for a better-quality narrative (slower than the 8B extractor).
_NIM_MODEL = "meta/llama-3.3-70b-instruct"


def _fmt(v, suffix="", na="n/a"):
    if v is None:
        return na
    try:
        return f"{float(v):,.2f}{suffix}"
    except Exception:
        return f"{v}{suffix}"


def _facts_block(snap: dict) -> str:
    """Build a compact, factual context block from the live snapshot."""
    m = snap.get("master", {}) or {}
    f = snap.get("fundamentals", {}) or {}
    me = snap.get("metrics", {}) or {}

    lines = [
        f"Company: {m.get('company_name', snap.get('symbol'))} ({snap.get('symbol')})",
        f"Sector: {m.get('sector', 'n/a')} | Industry: {m.get('industry', 'n/a')}",
        f"Market cap: {_fmt(m.get('market_cap_cr'), ' Cr')}",
        f"Last price: {_fmt(snap.get('latest_close'), '')} (as of {snap.get('latest_date','')})",
        "",
        "VALUATION & QUALITY:",
        f"  P/E: {_fmt(f.get('pe_ratio'))} | P/B: {_fmt(f.get('pb_ratio'))} | "
        f"P/S: {_fmt(f.get('ps_ratio'))} | EV/EBITDA: {_fmt(f.get('ev_ebitda'))}",
        f"  ROE: {_fmt(f.get('roe'), '%')} | Net margin: {_fmt(f.get('net_margin'), '%')} | "
        f"Operating margin: {_fmt(f.get('operating_margin'), '%')}",
        f"  D/E: {_fmt(f.get('debt_to_equity'))} | Current ratio: {_fmt(f.get('current_ratio'))} | "
        f"Dividend yield: {_fmt(f.get('dividend_yield'), '%')}",
        "",
        "PRICE ACTION & MOMENTUM:",
        f"  Returns — 1M: {_fmt(me.get('return_1m'),'%')}, 6M: {_fmt(me.get('return_6m'),'%')}, "
        f"1Y: {_fmt(me.get('return_1y'),'%')}, 3Y: {_fmt(me.get('return_3y'),'%')}",
        f"  50-DMA: {_fmt(me.get('dma_50'))} | 200-DMA: {_fmt(me.get('dma_200'))} | "
        f"RSI(14): {_fmt(me.get('rsi_14'))}",
        f"  Distance from 5Y high: {_fmt(me.get('distance_from_ath'),'%')}",
    ]

    rf = snap.get("red_flags")
    if rf:
        lines += ["", f"RED-FLAG SCAN: {rf}"]
    return "\n".join(lines)


def get_llm_analysis(snap: dict) -> dict:
    """
    Grounded senior-analyst read for a stock snapshot.

    Returns {"markdown": str, "ok": bool, "model": str}.
    """
    import httpx

    key = config.ai.nvidia_api_key
    if not key or not snap:
        return {"markdown": "", "ok": False, "model": None}

    facts = _facts_block(snap)
    name = (snap.get("master", {}) or {}).get("company_name", snap.get("symbol"))
    prompt = (
        f"You are a senior equity research analyst. Using ONLY the verified figures "
        f"below for {name}, write a concise, structured read. Do NOT invent any number "
        f"or fact not present here; if something is 'n/a', acknowledge the gap.\n\n"
        f"=== VERIFIED DATA ===\n{facts}\n=====================\n\n"
        f"Write in Markdown with these exact sections:\n"
        f"### Thesis\n(2-3 sentences on what the numbers say overall)\n"
        f"### Strengths\n(3-4 bullets, each citing a specific figure above)\n"
        f"### Risks & Watch-outs\n(3-4 bullets, each citing a specific figure)\n"
        f"### Valuation & Momentum\n(2-3 sentences interpreting P/E, P/B vs growth, and the "
        f"DMA/RSI/return picture)\n"
        f"### Analyst View\n(a cautious, educational summary — a leaning, NOT a buy/sell "
        f"recommendation)\n\n"
        f"Keep it tight and specific. This is educational content under SEBI norms, not "
        f"investment advice."
    )

    def _post(model: str, timeout: float) -> str:
        try:
            r = httpx.post(
                "https://integrate.api.nvidia.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content":
                            "You are a rigorous, grounded equity analyst. You never fabricate "
                            "numbers and never give direct buy/sell advice."},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": 900, "temperature": 0.3,
                },
                timeout=timeout,
            )
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
        except Exception:
            return ""
        return ""

    # Try the 70B model; if it's unavailable, fall back to the fast 8B one.
    for model, timeout in ((_NIM_MODEL, 90.0), ("meta/llama-3.1-8b-instruct", 45.0)):
        text = _post(model, timeout)
        if text and len(text) > 120:
            return {"markdown": _clean(text), "ok": True, "model": model}
    return {"markdown": "", "ok": False, "model": None}


def _clean(text: str) -> str:
    """Some reasoning-style models prepend their own scratchpad/instruction-echo
    before the actual answer. The required format always starts at the first
    '### ' heading — drop anything before it."""
    i = text.find("### ")
    return text[i:].strip() if i > 0 else text.strip()


__all__ = ["get_llm_analysis"]
