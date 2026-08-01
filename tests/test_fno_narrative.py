"""Checks for the two grounded F&O AI surfaces (offline, no LLM call).

They ask different questions, so the checks are mirror images: each facts block
must carry the numbers its own read needs, and must NOT carry the metrics that
render as <Stat> cards beside it (R15).
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.prompts import COMPLIANCE, GROUNDING, HOUSE_STYLE
from services import fno_narrative, fno_oi_read
from services.fno_narrative import _facts_block, get_fno_narrative, result
from services.fno_oi_read import get_oi_read

# A strike ladder with real per-leg change data, shaped like services.upstox
# ._parse_option_chain output after fno_analysis.classify_buildup has run.
def _leg(iv, oi, oi_change, price_chg, prev_close, delta, buildup):
    return {"iv": iv, "oi": oi, "oi_change": oi_change, "price_chg": price_chg,
            "prev_close": prev_close, "delta": delta, "volume": 1000, "ltp": 50.0,
            "buildup": buildup}


_STRIKES = [
    {"strike": 22900.0, "call": _leg(16.0, 1e5, 1e4, 1.0, 20.0, 0.95, "long_buildup"),
     "put": _leg(15.2, 9e5, 4e5, -3.0, 30.0, -0.05, "short_buildup")},
    {"strike": 23400.0, "call": _leg(13.0, 2e5, 2e4, 1.0, 40.0, 0.85, "long_buildup"),
     "put": _leg(12.6, 8e5, 3e5, -4.0, 55.0, -0.12, "short_buildup")},
    {"strike": 23650.0, "call": _leg(12.0, 3e5, 3e4, 1.0, 70.0, 0.70, "long_buildup"),
     "put": _leg(11.4, 7e5, 2e5, -5.0, 90.0, -0.25, "short_buildup")},
    {"strike": 23850.0, "call": _leg(11.5, 4e5, -5e4, 2.0, 120.0, 0.52, "short_covering"),
     "put": _leg(11.6, 4e5, 1e5, -6.0, 140.0, -0.48, "short_buildup")},
    {"strike": 24100.0, "call": _leg(11.0, 6e5, 5e5, 3.0, 60.0, 0.30, "long_buildup"),
     "put": _leg(11.9, 2e5, -8e4, -7.0, 220.0, -0.70, "long_unwinding")},
    {"strike": 24350.0, "call": _leg(11.8, 5e5, 2e5, 1.0, 30.0, 0.18, "long_buildup"),
     "put": _leg(None, 1e5, -1e4, -2.0, 380.0, -0.82, "long_unwinding")},
    {"strike": 24850.0, "call": _leg(14.4, 2e5, 1e4, 1.0, 10.0, 0.06, "long_buildup"),
     "put": _leg(15.0, 5e4, -5e3, -1.0, 830.0, -0.94, "long_unwinding")},
]

_PLAN = {
    "ok": True, "name": "NIFTY 50", "spot": 23869.6, "atm": 23850.0,
    "expiry": "2026-07-28", "pcr_oi": 0.68, "max_pain": 24000.0, "atm_iv": 11.54,
    "india_vix": 13.48,
    "oi_walls": {"call_wall": 25000.0, "put_wall": 23000.0},
    "expected_move": {"straddle": 258.1, "upper": 24127.8, "lower": 23611.4, "pct": 1.08},
    "bias": {"label": "BEARISH", "score": 32,
             "drivers": [{"name": "PCR", "detail": "0.68 (call-writing/heavy)", "delta": -8}]},
    "strategy": {"name": "Bear Put (debit) Spread", "iv_regime": "low",
                 "note": "A put debit spread; cheap IV favours long premium.", "anchors": {}},
    "levels": [{"label": "Max Pain", "price": 24000.0, "kind": "maxpain"},
               {"label": "Put OI Wall", "price": 23000.0, "kind": "support"}],
    "zones": [
        {"price": 23850.0, "lo": 23850.0, "hi": 23850.0, "kind": "resistance",
         "members": [{"label": "Pivot R1", "price": 23850.0, "kind": "resistance",
                      "crossed": True}],
         "crossed": True, "state": "BROKEN", "flip": "was resistance, now support",
         "dist_pct": -0.08, "strength": 65, "basis": "Pivot R1 23,850 is the only method here."},
        {"price": 24100.0, "lo": 24100.0, "hi": 24100.0, "kind": "resistance",
         "members": [{"label": "Call OI Wall", "price": 24100.0, "kind": "resistance",
                      "crossed": False}],
         "crossed": False, "state": "INTACT", "dist_pct": 0.97, "strength": 40,
         "basis": "Call OI Wall 24,100 is the only method here."},
    ],
    "buildup_summary": {
        "call": {"long_buildup": {"legs": 6, "oi_change": 760000.0},
                 "short_buildup": {"legs": 0, "oi_change": 0.0},
                 "short_covering": {"legs": 1, "oi_change": -50000.0},
                 "long_unwinding": {"legs": 0, "oi_change": 0.0}},
        "put": {"long_buildup": {"legs": 0, "oi_change": 0.0},
                "short_buildup": {"legs": 4, "oi_change": 1000000.0},
                "short_covering": {"legs": 0, "oi_change": 0.0},
                "long_unwinding": {"legs": 3, "oi_change": -95000.0}},
        "unclassified": {"call": 0, "put": 0}, "basis": "leg price"},
    "buildup_basis": "leg price",
    "delta_oi": {"call": 1234567.8, "put": 987654.3, "legs_without_greeks": 0},
    "strikes": _STRIKES,
    "expiries": ["2026-07-28", "2026-08-04", "2026-08-11", "2026-08-18"],
}

_TERM = {"ok": True, "cap": 4, "complete": False,
         "points": [{"expiry": "2026-07-28", "atm": 23850, "atm_iv": 11.54, "spot": 23869.6},
                    {"expiry": "2026-08-04", "atm": 23850, "atm_iv": 12.40, "spot": 23869.6},
                    {"expiry": "2026-08-11", "atm": 23850, "atm_iv": 13.05, "spot": 23869.6}],
         "unpriced": ["2026-08-18"]}

# The metrics that render as <Stat> cards beside each surface. A prompt that
# carries one of them invites the restatement R15 exists to stop.
_SPOT = "23,869.60"
_PCR = "0.68"
_MAX_PAIN = "24,000.00"
_VIX = "13.48"


# ----------------------------------------------------------------------
# R14 — every prompt composes the one shared grounding contract
# ----------------------------------------------------------------------

def test_both_systems_compose_the_shared_contract():
    for mod in (fno_narrative, fno_oi_read):
        for part in (GROUNDING, HOUSE_STYLE, COMPLIANCE):
            assert part in mod._SYSTEM, f"{mod.__name__} bypasses the shared contract"


# ----------------------------------------------------------------------
# /options — microstructure: skew + term structure
# ----------------------------------------------------------------------

def test_microstructure_facts_carry_the_surface():
    facts = _facts_block(_PLAN, _TERM)
    for token in ("NIFTY 50", "IV SMILE", "Risk reversal", "Wing spread",
                  "IV TERM STRUCTURE", "Front-to-back", "Delta-weighted OI",
                  "2026-08-11", "13.05"):
        assert token in facts, f"missing {token!r} in the microstructure facts"
    # The delta ladder renders both raw sums; only their ratio is handed over.
    assert "1.25x the put side" in facts
    for raw in ("1,234,567.80", "987,654.30"):
        assert raw not in facts, f"{raw!r} is on screen already — R15"


def test_microstructure_facts_omit_metrics_rendered_beside_it():
    facts = _facts_block(_PLAN, _TERM)
    for token in (_SPOT, _PCR, _MAX_PAIN, _VIX, "BEARISH"):
        assert token not in facts, f"{token!r} is on screen already — R15"


def test_microstructure_names_an_unpriced_expiry_instead_of_dropping_it():
    facts = _facts_block(_PLAN, _TERM)
    assert "No live ATM quote for: 2026-08-18" in facts
    assert "not zero" in facts


def test_microstructure_survives_a_missing_term_structure():
    facts = _facts_block(_PLAN, None)
    assert "IV TERM STRUCTURE: unavailable" in facts


def test_smile_names_an_unquoted_leg_rather_than_zeroing_it():
    # 24350 put has iv=None; it is the +2% sample against spot 23,869.6.
    facts = _facts_block(_PLAN, _TERM)
    assert "Legs with no live IV: 1 of 14" in facts


# ----------------------------------------------------------------------
# /fno — the OI read: where the money moved
# ----------------------------------------------------------------------

def test_oi_read_facts_carry_the_change_data():
    facts = fno_oi_read._facts_block(_PLAN)
    for token in ("BIGGEST OI MOVES, CALL SIDE", "BIGGEST OI MOVES, PUT SIDE",
                  "BUILD-UP QUADRANT MIX", "classified from: leg price",
                  "LEVEL ZONES THAT FLIPPED", "was resistance, now support",
                  "24,100", "+5.0L"):
        assert token in facts, f"missing {token!r} in the OI-read facts"


def test_oi_read_facts_omit_metrics_rendered_beside_it():
    facts = fno_oi_read._facts_block(_PLAN)
    for token in (_SPOT, _PCR, _MAX_PAIN, _VIX, "BEARISH"):
        assert token not in facts, f"{token!r} is on screen already — R15"


def test_oi_read_never_hands_a_zone_basis_to_the_model():
    """The basis string renders verbatim in the level ladder. A model given it
    would paraphrase it, which is the exact R15 failure."""
    facts = fno_oi_read._facts_block(_PLAN)
    for z in _PLAN["zones"]:
        assert z["basis"] not in facts


def test_oi_read_states_when_nothing_flipped():
    plan = {**_PLAN, "zones": [{**_PLAN["zones"][1]}]}
    facts = fno_oi_read._facts_block(plan)
    assert "none — no level has been crossed this session" in facts


def test_oi_read_ranks_strikes_by_absolute_oi_change():
    movers = fno_oi_read._movers(_STRIKES, _PLAN["spot"], "call")
    assert movers[0].startswith("  24,100"), movers[0]        # +5.0L, the largest
    assert "short covering" in "\n".join(movers)              # sign, not magnitude


# ----------------------------------------------------------------------
# Shared: SEBI framing and the degraded-answer guard
# ----------------------------------------------------------------------

_BANNED = re.compile(r"\b(buy|sell|accumulate|exit|target price|stop.?loss)\b", re.I)


def test_neither_prompt_instructs_the_reader():
    """The role sentence and the section spec are ours; the shared COMPLIANCE
    block legitimately says the words in order to ban them, so it is excluded."""
    for build, plan in ((lambda: fno_narrative._build_prompt(_PLAN, _TERM), _PLAN),
                        (lambda: fno_oi_read._build_prompt(_PLAN), _PLAN)):
        text = build()
        assert not _BANNED.search(text), _BANNED.search(text).group(0)
    for mod in (fno_narrative, fno_oi_read):
        role = mod._SYSTEM.replace(GROUNDING, "").replace(HOUSE_STYLE, "").replace(COMPLIANCE, "")
        assert not _BANNED.search(role)


def test_both_surfaces_guard_a_bad_plan():
    assert get_fno_narrative({})["ok"] is False
    assert get_fno_narrative({"ok": False})["ok"] is False
    assert get_oi_read({})["ok"] is False
    assert get_oi_read({"ok": False})["ok"] is False


def test_a_degraded_answer_is_not_reported_as_good():
    """`ok` is what the API layer keys its cache eviction on, so an answer that
    followed none of the requested sections must not claim success."""
    headings = ("Skew", "Term Structure")
    assert result("I'm sorry, I cannot access real-time data. " * 5, headings)["ok"] is False
    assert result("### Skew\ntoo short", headings)["ok"] is False
    good = "### Skew\n" + "The put wing is bid against the calls. " * 6
    assert result(good, headings)["ok"] is True
    # '##' instead of '###' is still the requested structure, not a failure.
    assert result("## Term Structure\n" + "Front is cheap to the back. " * 8,
                  headings)["ok"] is True


def test_a_degraded_surface_is_not_cached_as_a_good_one():
    """The API layer's half of the same guard: `ok: False` must be evicted so
    the next caller retries, instead of the wreck being served for 15 minutes."""
    from api.server import _cached_llm, _cache

    calls = []

    def produce(arg):
        calls.append(arg)
        return {"ok": False, "markdown": ""}

    _cache.pop("t:degraded", None)
    _cached_llm("t:degraded", produce, "nifty50", 900)
    assert "t:degraded" not in _cache
    _cached_llm("t:degraded", produce, "nifty50", 900)
    assert len(calls) == 2, "a degraded answer was served from cache"

    good = lambda arg: {"ok": True, "markdown": "x" * 200}
    _cache.pop("t:good", None)
    _cached_llm("t:good", good, "nifty50", 900)
    assert "t:good" in _cache


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
    print("OK — both F&O AI surfaces")
