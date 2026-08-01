"""
ARTHA Terminal - F&O microstructure read (the /options AI surface)

Answers ONE question: what does the volatility surface price in — the skew
across strikes and the term structure across expiries.

It used to narrate market structure and "how the levels trade" as well. Both
of those are a delta read on the level map, they belong to /fno (see
services/fno_oi_read.py), and both restated figures rendered as <Stat> cards
inches away. A model summarising "PCR = 1.14" adds nothing (R15), so this
surface is given the SHAPE of the surface — sampled smile, risk reversals,
wing spreads, term slope — and asked what the shape implies, never to read the
samples back.

The maths is done in Python; the LLM only interprets. Grounding, style and SEBI
framing come from agent.prompts, the one contract every ARTHA prompt composes;
this file adds only the role sentence.

Runs on agent.llm_client's "deep" tier chain, so provider fallback and
rate-limit cooldowns are handled in one place rather than here.
"""

from __future__ import annotations

from datetime import date

from agent.prompts import COMPLIANCE, GROUNDING, HOUSE_STYLE

_SYSTEM = (
    f"{GROUNDING}\n\n{HOUSE_STYLE}\n\n{COMPLIANCE}\n\n"
    "You are a senior F&O/derivatives strategist for Indian index options, "
    "reading the implied-volatility surface — the skew across strikes and the "
    "term structure across expiries — for what it prices in."
)

# Moneyness steps the smile is sampled at. The OTM leg is read at each one
# (put below spot, call above) because that is the leg carrying the volume
# there, which is what makes the two wings comparable at all.
_MONEYNESS = (-4.0, -2.0, -1.0, 1.0, 2.0, 4.0)

# Risk-reversal distances (% OTM), put IV minus call IV at the same distance.
_RR_STEPS = (1.0, 2.0)

_HEADINGS = ("Skew", "Term Structure", "What The Chain Is Pricing")


def _fmt(v, suffix=""):
    if v is None:
        return "n/a"
    try:
        return f"{float(v):,.2f}{suffix}"
    except Exception:
        return f"{v}{suffix}"


def _nearest(strikes: list[dict], target: float) -> dict | None:
    return min(strikes, key=lambda s: abs(s["strike"] - target)) if strikes else None


def _iv(row: dict | None, side: str) -> float | None:
    return ((row or {}).get(side) or {}).get("iv")


def _smile_block(spot: float | None, strikes: list[dict]) -> str:
    """The OTM smile sampled at fixed moneyness, plus both risk reversals and
    the wing spreads against ATM.

    A leg Upstox never priced (`iv` is None — services.upstox._greek nulls the
    literal 0.0 thin-quote print) is named as unquoted, never interpolated and
    never carried as a zero (R17).
    """
    if not spot or not strikes:
        return "IV smile: unavailable — no live chain."

    seen: set[float] = set()

    def row(m: float) -> str:
        s = _nearest(strikes, spot * (1 + m / 100))
        if s is None:
            return ""
        seen.add(s["strike"])
        side = "put" if m < 0 else "call"
        iv = _iv(s, side)
        return (f"  {m:+.1f}%  {s['strike']:,.0f} {side:<4} "
                f"IV {_fmt(iv) if iv is not None else 'no live quote'}")

    atm = _nearest(strikes, spot)
    lines = ["IV SMILE (OTM leg at each moneyness step — put below spot, call above):"]
    lines += [r for r in (row(m) for m in _MONEYNESS if m < 0) if r]
    if atm:
        lines.append(f"   ATM   {atm['strike']:,.0f}      "
                     f"call IV {_fmt(_iv(atm, 'call'))} | put IV {_fmt(_iv(atm, 'put'))}")
    lines += [r for r in (row(m) for m in _MONEYNESS if m > 0) if r]

    rr = []
    for m in _RR_STEPS:
        p = _iv(_nearest(strikes, spot * (1 - m / 100)), "put")
        c = _iv(_nearest(strikes, spot * (1 + m / 100)), "call")
        rr.append(f"{m:g}% OTM {p - c:+.2f}" if p is not None and c is not None
                  else f"{m:g}% OTM n/a")
    lines.append(f"Risk reversal (OTM put IV - OTM call IV): {' | '.join(rr)}")

    wings = []
    for m, side in ((_MONEYNESS[0], "put"), (_MONEYNESS[-1], "call")):
        w = _iv(_nearest(strikes, spot * (1 + m / 100)), side)
        a = _iv(atm, side)
        wings.append(f"{abs(m):g}% OTM {side} {w - a:+.2f} vs ATM"
                     if w is not None and a is not None else f"{abs(m):g}% OTM {side} n/a")
    lines.append(f"Wing spread: {' | '.join(wings)}")

    legs = [(s.get(side) or {}) for s in strikes for side in ("call", "put")]
    unquoted = sum(1 for l in legs if l.get("iv") is None)
    lines.append(f"Legs with no live IV: {unquoted} of {len(legs)}")
    return "\n".join(lines)


def _term_block(term: dict | None) -> str:
    """ATM IV per expiry across the nearest few expiries (services.fno_service
    .term_structure). A partial curve is stated as partial — the expiries with
    no live ATM quote are named, never plotted or implied at zero."""
    pts = (term or {}).get("points") or []
    if not pts:
        return "IV TERM STRUCTURE: unavailable — no expiry returned a live ATM quote."
    lines = [f"IV TERM STRUCTURE (ATM IV per expiry, nearest {(term or {}).get('cap', len(pts))} listed):"]
    lines += [f"  {p['expiry']}  ATM {_fmt(p.get('atm'))}  IV {_fmt(p.get('atm_iv'))}"
              for p in pts]
    if len(pts) > 1:
        days = (date.fromisoformat(pts[-1]["expiry"]) - date.fromisoformat(pts[0]["expiry"])).days
        lines.append(f"  Front-to-back: {pts[-1]['atm_iv'] - pts[0]['atm_iv']:+.2f} IV points "
                     f"over {days} days")
    if (term or {}).get("unpriced"):
        lines.append(f"  No live ATM quote for: {', '.join(term['unpriced'])} — "
                     f"absent from the curve above, not zero")
    return "\n".join(lines)


def _facts_block(plan: dict, term: dict | None = None) -> str:
    """Compact, factual microstructure context from the deterministic plan.

    Deliberately carries no spot, PCR, max pain, India VIX or bias: all of them
    render beside this surface, and a model handed them writes a restatement
    (R15). Strike and expiry numbers are coordinates for the shape, not metrics.
    """
    strikes = plan.get("strikes") or []
    d = plan.get("delta_oi") or {}
    # The two raw sums render as the delta ladder on the same page, so only the
    # RATIO between them is handed over — it is the one thing the bars do not
    # state, and a model given the sums writes them back out (observed live).
    ratio = (f"{d['call'] / d['put']:.2f}x" if d.get("call") and d.get("put")
             else "unavailable")
    return "\n".join([
        f"Index: {plan.get('name')} | Expiry: {plan.get('expiry')} | "
        f"{len(strikes)} strikes loaded | "
        f"{len(plan.get('expiries') or [])} expiries listed",
        "",
        _smile_block(plan.get("spot"), strikes),
        "",
        _term_block(term),
        "",
        f"Delta-weighted OI (sum of |delta| x OI): call side is {ratio} the put side "
        f"| {d.get('legs_without_greeks', 0)} legs without live greeks",
    ])


def _build_prompt(plan: dict, term: dict | None = None) -> str:
    facts = _facts_block(plan, term)
    return (
        f"Using the verified figures below for {plan.get('name')} index options, "
        f"read the volatility surface.\n\n"
        f"=== VERIFIED DATA ===\n{facts}\n=====================\n\n"
        f"Strike prices, expiry dates and moneyness steps are COORDINATES that locate "
        f"the shape — never present one as a finding.\n"
        f"Do not state the spot price, PCR, max pain, India VIX, the ATM IV or the bias: "
        f"every one of them is already rendered beside this text, and repeating it adds "
        f"nothing. Cite at most one figure per bullet, and only as the anchor for a claim "
        f"about the shape.\n\n"
        f"Write in Markdown with these exact sections:\n"
        f"### Skew\n(2-3 sentences on the SHAPE of the smile: which wing is bid, how "
        f"steep it is against the other, and what that pricing says about which tail the "
        f"market is paying to cover. Read the shape — do not list the sampled IVs back.)\n"
        f"### Term Structure\n(2-3 sentences: is the front expiry cheap or rich against "
        f"the back, and what the slope implies about where uncertainty sits in time. Name "
        f"any expiry with no live quote rather than passing over it.)\n"
        f"### What The Chain Is Pricing\n(2-3 bullets tying the skew and the term slope "
        f"together with the delta-weighted exposure — what a reader learns from this "
        f"microstructure that the individual figures on the page do not say. Describe what "
        f"the surface prices and stop there: do not name, prefer or rank any strategy, "
        f"position or structure for the reader. End on the soft signal only, "
        f"HOLD/WATCH/REVIEW, describing the state of the surface.)"
    )


def _clean(text: str) -> str:
    """Some reasoning-style models (e.g. Nemotron) prepend their own scratchpad
    /instruction-echo before the actual answer. The required format always
    starts at the first '### ' heading — drop anything before it."""
    i = text.find("### ")
    return text[i:].strip() if i > 0 else text.strip()


def result(text: str | None, headings: tuple[str, ...]) -> dict:
    """The one markdown-result contract both F&O AI surfaces return.

    A model that answered without a single one of the requested sections did
    not follow the format — an apology, a refusal or a truncated fragment all
    land there. That is a DEGRADED answer, and `ok: False` is what stops the
    API layer caching it for 15 minutes as though it were a good one (this
    project has been bitten by exactly that: a news read returned 2 of 18 items
    after a mid-call 429 and cached it).

    Section names are matched without their '###', so a model that emitted
    '##' still counts as having followed the structure.
    """
    md = _clean(text or "")
    low = md.lower()
    good = len(md) > 120 and any(h.lower() in low for h in headings)
    return {"markdown": md if good else "", "ok": good, "model": "router" if good else None}


def get_fno_narrative(plan: dict, term: dict | None = None) -> dict:
    """
    Grounded microstructure read of one index's volatility surface.

    `term` is services.fno_service.term_structure() output (optional — the
    term-structure section says "unavailable" without it rather than guessing).
    Runs on the router's "deep" chain. Returns {"markdown", "ok", "model"}.
    """
    from agent.llm_client import complete

    if not plan or not plan.get("ok"):
        return {"markdown": "", "ok": False, "model": None}

    text = complete(_SYSTEM, _build_prompt(plan, term), task_shape="deep")
    return result(text, _HEADINGS)


__all__ = ["get_fno_narrative", "result"]
