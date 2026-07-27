"""Checks for the grounded F&O narrative facts block (offline, no LLM call)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.fno_narrative import _facts_block, get_fno_narrative

_PLAN = {
    "ok": True, "name": "NIFTY 50", "spot": 23869.6, "atm": 23850.0,
    "expiry": "2026-07-28", "pcr_oi": 0.68, "max_pain": 24000.0, "atm_iv": 11.54,
    "india_vix": 13.48,
    "oi_walls": {"call_wall": 25000.0, "put_wall": 23000.0},
    "expected_move": {"straddle": 258.1, "upper": 24127.8, "lower": 23611.4, "pct": 1.08},
    "bias": {"label": "BEARISH", "score": 32,
             "drivers": [{"name": "PCR", "detail": "0.68 (call-writing/heavy)", "delta": -8}]},
    "strategy": {"name": "Bear Put (debit) Spread", "iv_regime": "low",
                 "note": "Buy a put debit spread; cheap IV favours long premium.", "anchors": {}},
    "levels": [{"label": "Max Pain", "price": 24000.0, "kind": "maxpain"},
               {"label": "Put OI Wall (S)", "price": 23000.0, "kind": "support"}],
}


def test_facts_block_grounded():
    facts = _facts_block(_PLAN)
    # every headline number must appear verbatim so the LLM can't drift
    for token in ("NIFTY 50", "23,869.60", "0.68", "24,000.00", "25,000.00",
                  "23,000.00", "11.54%", "13.48", "BEARISH", "Bear Put"):
        assert token in facts, f"missing {token!r} in facts block"


def test_narrative_guards_bad_plan():
    assert get_fno_narrative({})["ok"] is False
    assert get_fno_narrative({"ok": False})["ok"] is False


if __name__ == "__main__":
    test_facts_block_grounded()
    test_narrative_guards_bad_plan()
    print("OK — fno narrative facts block")
