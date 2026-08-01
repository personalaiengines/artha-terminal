"""
ARTHA Terminal - F&O OI read (the /fno AI surface)

Answers ONE question: where did the money move since the prior session, and
what does that say about where the writers moved their defence.

This is a CHANGE read, not a restatement. It is deliberately blind to spot,
PCR, max pain, ATM IV and India VIX — every one of those renders as a <Stat>
card beside this widget, and a model narrating "PCR = 1.14" adds nothing (R15).
It is given only change data, all of it already computed deterministically:

  * the strikes that moved the most open interest, with the build-up quadrant
    services.fno_analysis.classify_buildup assigned each leg,
  * the aggregate quadrant mix per side and the provenance of the price change
    that classified it (`buildup_basis`),
  * which confluence zone flipped side this session.

No day-over-day snapshot is needed or attempted: `prev_oi` and `close_price`
ride on every leg, so the change is in today's chain. Nothing persists a
per-session plan, so a real day-over-day diff is not available — and is not
invented (R17).

The maths is done in Python; the LLM only interprets. Grounding, style and SEBI
framing come from agent.prompts, the one contract every ARTHA prompt composes;
this file adds only the role sentence. Runs on the "deep" tier chain.
"""

from __future__ import annotations

from agent.prompts import COMPLIANCE, GROUNDING, HOUSE_STYLE
from services.fno_narrative import result

_SYSTEM = (
    f"{GROUNDING}\n\n{HOUSE_STYLE}\n\n{COMPLIANCE}\n\n"
    "You are a senior F&O/derivatives strategist for Indian index options, "
    "reading where open interest moved this session and what that says about "
    "where the option writers have moved their defence."
)

# Strikes shown per side. Enough to see whether the flow is concentrated at one
# price or spread along a ladder; short enough that the model reads a pattern
# instead of transcribing a table.
_TOP_N = 5

# Zones handed over purely so a strike can be located against the level map.
_TOP_ZONES = 3

_QUADRANT_LABEL = {
    "long_buildup": "long build-up",
    "short_buildup": "short build-up",
    "short_covering": "short covering",
    "long_unwinding": "long unwinding",
}

_HEADINGS = ("Where The Defence Moved", "What The Build-Up Says", "The Level That Flipped")


def _lakh(v) -> str:
    """OI in lakh contracts — the unit the desk and the UI both use."""
    return "n/a" if v is None else f"{v / 1e5:+,.1f}L"


def _movers(strikes: list[dict], spot: float, side: str) -> list[str]:
    """The `_TOP_N` strikes on one side by absolute OI change.

    Distance from spot is pre-computed as a percentage so the prompt never has
    to carry the spot price itself (R15 — spot renders as a <Stat> beside this).
    """
    rows = [s for s in strikes if (s.get(side) or {}).get("oi_change")]
    rows.sort(key=lambda s: abs(s[side]["oi_change"]), reverse=True)
    out = []
    for s in rows[:_TOP_N]:
        leg = s[side]
        dist = (s["strike"] - spot) / spot * 100
        chg = leg.get("price_chg")
        prev = leg.get("prev_close")
        pct = f"{chg / prev * 100:+.1f}%" if chg is not None and prev else "n/a"
        q = _QUADRANT_LABEL.get(leg.get("buildup"), "unclassified")
        out.append(f"  {s['strike']:,.0f} ({dist:+.2f}% from spot): "
                   f"OI {_lakh(leg['oi_change'])} to {(leg.get('oi') or 0) / 1e5:,.1f}L, "
                   f"leg price {pct}, {q}")
    return out


def _quadrant_line(cell: dict, side: str) -> str:
    parts = [f"{_QUADRANT_LABEL[q]} {cell[q]['legs']} legs ({_lakh(cell[q]['oi_change'])})"
             for q in _QUADRANT_LABEL if cell.get(q, {}).get("legs")]
    return f"  {side}: " + (", ".join(parts) if parts else "nothing classified")


def _facts_block(plan: dict) -> str:
    """Change-only context from the deterministic plan (no invented data).

    Carries no spot, PCR, max pain, ATM IV, India VIX or bias — see the module
    docstring. Zone rows are here to LOCATE the OI shifts against the level map,
    not to be described: their `basis` strings render verbatim in the ladder
    beside this text and are never handed to a model.
    """
    spot = plan.get("spot")
    strikes = plan.get("strikes") or []
    summary = plan.get("buildup_summary") or {}
    zones = plan.get("zones") or []

    lines = [f"Index: {plan.get('name')} | Expiry: {plan.get('expiry')} | "
             f"{len(strikes)} strikes loaded"]

    if spot and strikes:
        lines += ["", "BIGGEST OI MOVES, CALL SIDE (by absolute change since the prior session):"]
        lines += _movers(strikes, spot, "call") or ["  none — no call leg changed OI"]
        lines += ["", "BIGGEST OI MOVES, PUT SIDE:"]
        lines += _movers(strikes, spot, "put") or ["  none — no put leg changed OI"]
    else:
        lines += ["", "Per-strike OI change: unavailable — no live chain."]

    lines += ["", "BUILD-UP QUADRANT MIX (whole chain):"]
    for side in ("call", "put"):
        cell = summary.get(side)
        lines.append(_quadrant_line(cell, side) if cell else f"  {side}: unavailable")
    unc = summary.get("unclassified") or {}
    lines.append(f"  unclassified (leg price or OI did not move): "
                 f"call {unc.get('call', 0)}, put {unc.get('put', 0)}")
    lines.append(f"  classified from: {plan.get('buildup_basis') or 'nothing — no leg could be classified'}")

    crossed = [z for z in zones if z.get("crossed")]
    lines += ["", "LEVEL ZONES THAT FLIPPED SIDE THIS SESSION:"]
    if crossed:
        lines += [f"  {z['price']:,.0f} ({', '.join(m['label'] for m in z.get('members', []))}) "
                  f"- {z.get('flip', 'crossed')}, strength {z.get('strength')}/100"
                  for z in crossed]
    else:
        lines.append("  none — no level has been crossed this session")

    strong = sorted(zones, key=lambda z: z.get("strength") or 0, reverse=True)[:_TOP_ZONES]
    lines += ["", "STRONGEST LEVEL ZONES (coordinates only, to locate the OI above):"]
    lines += [f"  {z['price']:,.0f} ({z.get('dist_pct', 0):+.2f}% from spot) {z.get('state')} "
              f"strength {z.get('strength')}/100" for z in strong] or ["  none computed"]
    return "\n".join(lines)


def _build_prompt(plan: dict) -> str:
    facts = _facts_block(plan)
    return (
        f"Using the verified change data below for {plan.get('name')} index options, "
        f"read where open interest moved this session.\n\n"
        f"=== VERIFIED DATA ===\n{facts}\n=====================\n\n"
        f"Strike prices and zone prices are COORDINATES that locate the flow — never "
        f"present one as a finding.\n"
        f"Do not state the spot price, PCR, max pain, the ATM IV or India VIX: every one "
        f"of them is already rendered beside this text, and repeating it adds nothing. Do "
        f"not restate the quadrant counts or the zone descriptions back — they render "
        f"beside this text too. Cite at most one figure per bullet, and only as the anchor "
        f"for a claim about positioning.\n\n"
        f"Write in Markdown with these exact sections:\n"
        f"### Where The Defence Moved\n(2-3 bullets: which side added open interest and "
        f"which side shed it, and whether the writers rolled their strikes up, rolled them "
        f"down, or held the same prices. Say whether the flow is concentrated at one strike "
        f"or spread along a ladder.)\n"
        f"### What The Build-Up Says\n(2-3 sentences reading the MIX of quadrants: what the "
        f"balance of fresh writing against covering says about conviction on each side, and "
        f"whether the two sides agree or contradict each other.)\n"
        f"### The Level That Flipped\n(2-3 sentences on the zone that crossed: what the open "
        f"interest sitting around that price says about whether the flip is being defended "
        f"or abandoned. If nothing flipped, say so in one line and instead read the heaviest "
        f"fresh OI against the nearest strong zone.)\n\n"
        f"End on the soft signal only, HOLD/WATCH/REVIEW, describing the state of the "
        f"positioning — never a position for the reader."
    )


def get_oi_read(plan: dict) -> dict:
    """
    Grounded "where did the money move" read of one index's option chain.

    Runs on the router's "deep" chain. Returns {"markdown", "ok", "model"};
    `ok` is False for a degraded answer so the API layer does not cache it.
    """
    from agent.llm_client import complete

    if not plan or not plan.get("ok"):
        return {"markdown": "", "ok": False, "model": None}

    return result(complete(_SYSTEM, _build_prompt(plan), task_shape="deep"), _HEADINGS)


__all__ = ["get_oi_read"]
