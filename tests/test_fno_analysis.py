"""Deterministic checks for the F&O analysis engine (offline, hand-computed)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import fno_analysis as fno


def mk(strike, ce_oi, pe_oi, *, ce_ltp=None, pe_ltp=None,
       ce_iv=None, pe_iv=None, ce_chg=0, pe_chg=0):
    """Build one parsed-chain strike row."""
    return {
        "strike": strike,
        "call": {"oi": ce_oi, "prev_oi": None, "oi_change": ce_chg,
                 "ltp": ce_ltp, "iv": ce_iv, "volume": None, "delta": None},
        "put": {"oi": pe_oi, "prev_oi": None, "oi_change": pe_chg,
                "ltp": pe_ltp, "iv": pe_iv, "volume": None, "delta": None},
    }


def test_max_pain_hand_computed():
    # Pain at E: E=100→350, E=105→100, E=110→350  ⇒ min at 105.
    strikes = [mk(100, 10, 100), mk(105, 50, 50), mk(110, 100, 10)]
    assert fno.max_pain(strikes) == 105


def test_pcr_and_oi_walls():
    strikes = [mk(100, 10, 100), mk(105, 50, 50), mk(110, 100, 10)]
    assert fno.pcr_oi(strikes) == 1.0          # 160 put / 160 call
    walls = fno.oi_walls(strikes)
    assert walls["call_wall"] == 110           # max call OI
    assert walls["put_wall"] == 100            # max put OI


def test_expected_move_from_atm_straddle():
    strikes = [mk(100, 10, 10, ce_ltp=25, pe_ltp=5),
               mk(105, 20, 20, ce_ltp=20, pe_ltp=18),
               mk(110, 10, 10, ce_ltp=8, pe_ltp=30)]
    em = fno.expected_move(105, strikes)       # ATM = 105, straddle = 38
    assert em["straddle"] == 38
    assert em["upper"] == 143 and em["lower"] == 67


def test_bias_direction():
    # High PCR (put-writing) → bullish; low PCR (call-writing) → bearish.
    # mp passed == spot to neutralize the max-pain driver, oi_change=0.
    bull = [mk(100, 20, 300), mk(105, 20, 300), mk(110, 20, 300)]
    bear = [mk(100, 300, 20), mk(105, 300, 20), mk(110, 300, 20)]
    assert fno.options_flow_bias(bull, 105, 105)["label"] == "BULLISH"
    assert fno.options_flow_bias(bear, 105, 105)["label"] == "BEARISH"
    assert fno.options_flow_bias([mk(100, 100, 100)], 100, 100)["label"] == "NEUTRAL"


def test_analyze_end_to_end():
    strikes = [mk(100, 10, 100, ce_ltp=25, pe_ltp=5, ce_iv=16, pe_iv=17),
               mk(105, 50, 50, ce_ltp=20, pe_ltp=18, ce_iv=16, pe_iv=14),
               mk(110, 100, 10, ce_ltp=8, pe_ltp=30, ce_iv=15, pe_iv=16)]
    chain = {"spot": 105, "strikes": strikes, "expiry": "2026-07-28"}
    out = fno.analyze(chain, prev_ohlc={"high": 112, "low": 98})

    assert out["ok"] is True
    assert out["max_pain"] == 105
    assert out["atm"] == 105
    assert out["oi_walls"] == {"call_wall": 110, "put_wall": 100}
    # levels include option-derived + prev-day structure, all priced
    labels = {l["label"] for l in out["levels"]}
    assert {"Max Pain", "Call OI Wall (R)", "Put OI Wall (S)",
            "Prev Day High", "Prev Day Low"} <= labels
    assert all(isinstance(l["price"], (int, float)) for l in out["levels"])

    # empty chain guarded
    assert fno.analyze({"spot": None, "strikes": []})["ok"] is False


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"OK — {name}")
