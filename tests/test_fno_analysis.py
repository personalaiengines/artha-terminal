"""Deterministic checks for the F&O analysis engine (offline, hand-computed)."""

import re
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


def test_expected_move_is_unavailable_when_the_atm_straddle_is_unquoted():
    # A far, untraded expiry prints ltp 0.0 on both ATM legs. The band that
    # falls out of that is zero-width and centred on spot — it must read as
    # "unavailable", not as a measured move of nothing.
    strikes = [mk(100, 10, 10, ce_ltp=0.0, pe_ltp=0.0),
               mk(105, 20, 20, ce_ltp=0.0, pe_ltp=0.0)]
    assert fno.expected_move(105, strikes) is None


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
    # The (R)/(S) suffixes were dropped from the wall labels: which side a level
    # is on is now derived from spot, so baking it into the name could contradict
    # the kind. Nothing here crosses spot (105), so every kind keeps its natural side.
    assert {"Max Pain", "Call OI Wall", "Put OI Wall",
            "Prev Day High", "Prev Day Low"} <= labels
    assert all(isinstance(l["price"], (int, float)) for l in out["levels"])
    assert not any(l["crossed"] for l in out["levels"])


def test_support_and_resistance_flip_when_price_crosses_them():
    """S/R is a position relative to price, not a fixed property of a level.

    Regression: kind was assigned from the level's NAME — "Prev Day High" was
    always resistance, Pivot S1 always support — so once price crossed one, the
    chart kept asserting the old side. A broken resistance IS the next support.
    """
    strikes = [mk(100, 10, 100, ce_ltp=25, pe_ltp=5, ce_iv=16, pe_iv=17),
               mk(105, 50, 50, ce_ltp=20, pe_ltp=18, ce_iv=16, pe_iv=14),
               mk(110, 100, 10, ce_ltp=8, pe_ltp=30, ce_iv=15, pe_iv=16)]
    # Spot gaps ABOVE the previous day's high (112) and above the call wall (110).
    chain = {"spot": 115, "strikes": strikes, "expiry": "2026-07-28"}
    lv = {l["label"]: l for l in fno.analyze(chain, prev_ohlc={"high": 112, "low": 98})["levels"]}

    assert lv["Prev Day High"]["kind"] == "support", "price is above it — it is support now"
    assert lv["Prev Day High"]["crossed"] is True
    assert lv["Call OI Wall"]["kind"] == "support"
    assert lv["Call OI Wall"]["crossed"] is True
    # Untouched levels keep their side and are not flagged.
    assert lv["Prev Day Low"]["kind"] == "support"
    assert lv["Prev Day Low"]["crossed"] is False
    # Magnets and boundaries are not S/R and must not be reclassified.
    assert lv["Max Pain"]["kind"] == "maxpain"

    # empty chain guarded
    assert fno.analyze({"spot": None, "strikes": []})["ok"] is False


# ----------------------------------------------------------------------
# Confluence zones / strength / structure read
# Live NIFTY numbers from 2026-07-31 (spot 24,317.15) so the clustering is
# exercised against the real spacing, not a spacing invented to make it work.
# ----------------------------------------------------------------------

SPOT = 24317.15
EM = {"straddle": 220.85, "upper": 24538.0, "lower": 24096.4, "pct": 0.91}
WALLS_OI = {"call": {"oi": 8_400_000, "median": 2_100_000},
            "put": {"oi": 2_400_000, "median": 2_100_000}}


def lv(label, price, kind, crossed=False):
    """One build_levels() row."""
    return {"label": label, "price": price, "kind": kind, "crossed": crossed}


def zn(members, price=None, crossed=False):
    """One zone, hand-built, for scoring in isolation."""
    prices = [m["price"] for m in members]
    return {"price": price if price is not None else sum(prices) / len(prices),
            "lo": min(prices), "hi": max(prices), "members": members,
            "crossed": crossed}


def test_clustered_levels_form_one_zone_and_distant_ones_stay_apart():
    """Two methods naming the same price is the whole point of a zone.

    Pivot R1 24,377.7 and Prev Day High 24,342.9 are 0.14% apart — one zone.
    Pivot R2 24,438.2 is 0.39% away from it — its own zone.
    """
    levels = [lv("Pivot R1", 24377.7, "resistance"),
              lv("Prev Day High", 24342.9, "resistance"),
              lv("Pivot R2", 24438.2, "resistance")]
    zones = fno.level_zones(SPOT, levels)

    assert len(zones) == 2
    merged, alone = zones[0], zones[1]
    assert {m["label"] for m in merged["members"]} == {"Pivot R1", "Prev Day High"}
    assert merged["lo"] == 24342.9 and merged["hi"] == 24377.7
    assert merged["price"] == 24360.3                  # plain mean, no OI member
    assert [m["label"] for m in alone["members"]] == ["Pivot R2"]
    # complete linkage: a zone is never wider than the tolerance it claims
    assert (merged["hi"] - merged["lo"]) / SPOT * 100 <= fno.ZONE_TOL_PCT


def test_a_zone_prices_itself_at_the_oi_wall_strike():
    """Contracts sit at strikes; when a wall is in the zone, that is the price."""
    zones = fno.level_zones(SPOT, [lv("Pivot R1", 24377.7, "resistance"),
                                   lv("Call OI Wall", 24350.0, "resistance")])
    assert len(zones) == 1 and zones[0]["price"] == 24350.0


def test_strength_orders_confluence_and_oi_weight_above_a_lone_level():
    r1 = lv("Pivot R1", 24377.7, "resistance")
    lone = fno.zone_strength(zn([r1]), SPOT, EM, WALLS_OI)[0]
    pair = fno.zone_strength(zn([r1, lv("Prev Day High", 24342.9, "resistance")]),
                             SPOT, EM, WALLS_OI)[0]
    with_wall = fno.zone_strength(zn([r1, lv("Call OI Wall", 24350.0, "resistance")]),
                                  SPOT, EM, WALLS_OI)[0]
    assert lone < pair < with_wall <= 100

    # A wall that is NOT heavy against the median scores no OI points.
    flat = {"call": {"oi": 2_200_000, "median": 2_100_000}}
    thin = fno.zone_strength(zn([r1, lv("Call OI Wall", 24350.0, "resistance")]),
                             SPOT, EM, flat)[0]
    assert thin == pair
    # Crossing costs strength, and the basis says so.
    score, basis = fno.zone_strength(zn([r1], crossed=True), SPOT, EM, WALLS_OI)
    assert score < lone and "crossed since the prior session" in basis


def test_missing_expected_move_is_named_not_defaulted():
    """R17: an absent input is stated, never scored as if it were measured."""
    z = zn([lv("Pivot R1", 24377.7, "resistance"),
            lv("Prev Day High", 24342.9, "resistance")])
    with_band, band_basis = fno.zone_strength(z, SPOT, EM, WALLS_OI)
    without, no_basis = fno.zone_strength(z, SPOT, None, WALLS_OI)

    assert without < with_band
    assert "expected-move band" in band_basis
    assert no_basis.endswith("expected move unavailable.")
    assert "expected-move band" not in no_basis


def test_a_crossed_level_reads_broken_and_puts_the_map_under_review():
    strikes = [mk(100, 10, 100, ce_ltp=25, pe_ltp=5, ce_iv=16, pe_iv=17),
               mk(105, 50, 50, ce_ltp=20, pe_ltp=18, ce_iv=16, pe_iv=14),
               mk(110, 100, 10, ce_ltp=8, pe_ltp=30, ce_iv=15, pe_iv=16)]
    # Spot gapped above the prior day's high (112) and the call wall (110).
    out = fno.analyze({"spot": 115, "strikes": strikes, "expiry": "2026-07-28"},
                      prev_ohlc={"high": 112, "low": 98})
    zones = {z["members"][0]["label"]: z for z in out["zones"]}

    pdh = zones["Prev Day High"]
    assert pdh["state"] == "BROKEN" and pdh["crossed"] is True
    assert pdh["kind"] == "support" and pdh["flip"] == "was resistance, now support"
    assert zones["Prev Day Low"]["state"] == "INTACT"
    assert zones["Max Pain"]["kind"] == "maxpain"      # a magnet is not S/R

    assert out["structure"]["signal"] == "REVIEW"
    assert "2 levels flipped side" in out["structure"]["headline"]
    assert "Prev Day High 112.00 was resistance, now support" in out["structure"]["basis"]


def test_structure_state_returns_one_of_three_signals_or_says_it_cannot():
    levels = [lv("Pivot R1", 24377.7, "resistance"),
              lv("Prev Day High", 24342.9, "resistance"),
              lv("Pivot S1", 24221.9, "support"),
              lv("Prev Day Low", 24187.1, "support")]
    for spot in (23000.0, 24200.0, 24317.15, 24360.0, 25500.0):
        # kinds re-derived from spot the way build_levels does, so nothing here
        # asserts a side from a label.
        ls = [dict(l, kind=("resistance" if l["price"] > spot else "support"))
              for l in levels]
        st = fno.structure_state(spot, fno.level_zones(spot, ls, em=EM))
        assert st["signal"] in ("HOLD", "WATCH", "REVIEW")
        assert st["headline"] and st["basis"]

    # Spot 0.13% under the R1 + PDH confluence (strength 75) → WATCH.
    watch = fno.structure_state(24328.0, fno.level_zones(24328.0, [
        lv("Pivot R1", 24377.7, "resistance"), lv("Prev Day High", 24342.9, "resistance"),
        lv("Pivot S1", 24221.9, "support")], em=EM))
    assert watch["signal"] == "WATCH" and "strength" in watch["headline"]

    # No levels at all → no signal and an explicit "unavailable" (R17).
    empty = fno.structure_state(24317.15, [])
    assert empty["signal"] is None and "unavailable" in empty["headline"]
    assert fno.level_zones(None, levels) == [] and fno.level_zones(SPOT, []) == []


def test_every_number_in_a_zone_basis_comes_from_the_inputs():
    """R18: the basis is assembled from the inputs, never invented.

    Rendering each input through the same formatter the basis uses proves a
    token could only have come from an input value.
    """
    levels = [lv("Put OI Wall", 24000.0, "support"),
              lv("Exp-Move Lower", 24096.4, "range"),
              lv("Pivot S2", 24126.6, "support"),
              lv("Prev Day Low", 24187.1, "support"),
              lv("Pivot S1", 24221.9, "support"),
              lv("Max Pain", 24250.0, "maxpain"),
              lv("Pivot P", 24282.4, "pivot"),
              lv("Prev Day High", 24342.9, "resistance"),
              lv("Pivot R1", 24377.7, "resistance"),
              lv("Pivot R2", 24438.2, "resistance"),
              lv("Exp-Move Upper", 24538.0, "range"),
              lv("Call OI Wall", 24600.0, "resistance")]
    zones = fno.level_zones(SPOT, levels, em=EM, walls_oi=WALLS_OI)
    assert any(len(z["members"]) > 1 for z in zones), "the live spacing must confluence"

    for z in zones:
        allowed = {fno._px(m["price"]) for m in z["members"]}
        allowed |= {fno._px(EM["straddle"]), f"{(z['hi'] - z['lo']) / SPOT * 100:.2f}"}
        allowed |= {f"{w['oi'] / 1e5:.1f}" for w in WALLS_OI.values()}
        allowed |= {f"{w['median'] / 1e5:.1f}" for w in WALLS_OI.values()}
        # standalone numbers only — "S2" / "R1" are level names, not measurements
        for tok in re.findall(r"(?<![A-Za-z\d])\d[\d,]*(?:\.\d+)?", z["basis"]):
            assert tok in allowed, f"{tok!r} is not an input value — basis: {z['basis']}"


def test_no_signal_vocabulary_leaks_into_the_zone_or_structure_text():
    """R16: this engine describes the level map; it never instructs the reader."""
    banned = re.compile(r"\b(buy|sell|accumulate|exit|book|target|stop.?loss|"
                        r"long|short|entry)\b", re.I)
    levels = [lv("Pivot R1", 24377.7, "resistance"),
              lv("Prev Day High", 24342.9, "resistance"),
              lv("Call OI Wall", 24600.0, "resistance"),
              lv("Pivot S1", 24221.9, "support", crossed=True)]
    zones = fno.level_zones(SPOT, levels, em=EM, walls_oi=WALLS_OI)
    text = [z["basis"] for z in zones] + [z.get("flip", "") for z in zones]
    for st in (fno.structure_state(SPOT, zones),
               fno.structure_state(SPOT, []),
               fno.structure_state(24328.0, fno.level_zones(24328.0, levels[:2], em=EM))):
        text += [st["headline"], st["basis"]]
    for s in text:
        assert not banned.search(s), f"signal vocabulary in: {s}"


# ----------------------------------------------------------------------
# OI build-up quadrants / delta-weighted OI / percentile rank
# ----------------------------------------------------------------------

def leg(oi_change=None, price_chg=None, oi=None, delta=None):
    """One parsed leg, only the fields the enrichment reads."""
    return {"oi": oi, "oi_change": oi_change, "price_chg": price_chg, "delta": delta}


def test_buildup_truth_table():
    # price ↑ OI ↑ long · price ↓ OI ↑ short · price ↑ OI ↓ cover · price ↓ OI ↓ unwind
    assert fno.buildup(+5.0, +1000) == "long_buildup"
    assert fno.buildup(-5.0, +1000) == "short_buildup"
    assert fno.buildup(+5.0, -1000) == "short_covering"
    assert fno.buildup(-5.0, -1000) == "long_unwinding"


def test_buildup_refuses_a_flat_or_missing_print():
    # A zero change is not a quadrant, and neither is a missing one (R17).
    assert fno.buildup(0.0, 1000) is None
    assert fno.buildup(5.0, 0) is None
    assert fno.buildup(None, 1000) is None
    assert fno.buildup(5.0, None) is None


def test_classify_buildup_tags_legs_and_aggregates_per_side():
    strikes = [
        {"strike": 100, "call": leg(+1000, +5.0), "put": leg(-800, -2.0)},
        {"strike": 105, "call": leg(+500, +1.0), "put": leg(0, +3.0)},   # put unclassifiable
    ]
    out = fno.classify_buildup(strikes)
    # tagged in place — this is what the per-strike chip renders from
    assert strikes[0]["call"]["buildup"] == "long_buildup"
    assert strikes[0]["put"]["buildup"] == "long_unwinding"
    assert strikes[1]["put"]["buildup"] is None
    # aggregate agrees with the tags, because it is the same pass
    assert out["call"]["long_buildup"] == {"legs": 2, "oi_change": 1500.0}
    assert out["put"]["long_unwinding"] == {"legs": 1, "oi_change": -800.0}
    assert out["call"]["short_buildup"] == {"legs": 0, "oi_change": 0.0}
    assert out["unclassified"] == {"call": 0, "put": 1}
    assert out["basis"] == fno.BUILDUP_BASIS_LEG == "leg price"


def test_buildup_basis_is_none_when_nothing_could_be_classified():
    # No per-leg price change anywhere → no basis to claim (R17).
    out = fno.classify_buildup([{"strike": 100, "call": leg(+1000), "put": leg(-500)}])
    assert out["basis"] is None
    assert out["unclassified"] == {"call": 1, "put": 1}


def test_delta_weighted_oi_skips_legs_without_greeks():
    strikes = [
        {"strike": 100, "call": leg(oi=1000, delta=0.6), "put": leg(oi=2000, delta=-0.4)},
        # the SENSEX thin-quote artifact: real OI, greek printed as literally 0
        {"strike": 105, "call": leg(oi=5000, delta=0.0), "put": leg(oi=500, delta=None)},
    ]
    out = fno.delta_weighted_oi(strikes)
    assert out["call"] == 600.0          # 0.6×1000 only — the delta-0 leg is excluded
    assert out["put"] == 800.0           # |−0.4|×2000
    assert out["legs_without_greeks"] == 2


def test_delta_weighted_oi_reports_none_for_a_side_with_no_greeks_at_all():
    out = fno.delta_weighted_oi([{"strike": 100, "call": leg(oi=1000), "put": leg(oi=1000)}])
    assert out["call"] is None and out["put"] is None
    assert out["legs_without_greeks"] == 2


def test_percentile_rank_needs_a_real_window():
    assert fno.percentile_rank(list(range(59)), 30) is None      # 59 points: no claim
    assert fno.percentile_rank(list(range(60)), 30) is not None  # 60: the floor
    assert fno.percentile_rank(list(range(100)), None) is None


def test_percentile_rank_against_a_known_series():
    series = list(range(1, 101))                 # 1..100
    assert fno.percentile_rank(series, 25) == 25.0
    assert fno.percentile_rank(series, 100) == 100.0
    assert fno.percentile_rank(series, 0) == 0.0
    assert fno.percentile_rank([None] + series, 50) == 50.0     # Nones dropped


def test_analyze_emits_buildup_and_delta_blocks():
    strikes = [mk(100, 10, 100, ce_ltp=25, pe_ltp=5),
               mk(105, 50, 50, ce_ltp=20, pe_ltp=18, ce_chg=1000, pe_chg=-500),
               mk(110, 100, 10, ce_ltp=5, pe_ltp=30)]
    strikes[1]["call"]["price_chg"] = 2.0
    strikes[1]["put"]["price_chg"] = -1.0
    strikes[1]["call"]["delta"] = 0.5
    out = fno.analyze({"spot": 105.0, "strikes": strikes, "expiry": "2026-08-04"})
    assert out["buildup_basis"] == "leg price"
    assert out["buildup_summary"]["call"]["long_buildup"]["legs"] == 1
    assert out["buildup_summary"]["put"]["long_unwinding"]["legs"] == 1
    assert out["delta_oi"]["call"] == 25.0        # 0.5 × 50
    assert out["delta_oi"]["put"] is None
    assert out["delta_oi"]["legs_without_greeks"] == 5   # 6 legs, 1 has a delta


# SEBI (R16): the structure concept renders on /options. It may name a
# structure and describe how it is built; it may never instruct the reader.
_BANNED = re.compile(r"buy|sell|accumulate|exit|target|stop.?loss", re.I)
_REGIMES = [(None, "low"), (10.0, "low"), (22.0, "high")]


def test_structure_concept_carries_no_instruction_to_the_reader():
    walls = {"call_wall": 110, "put_wall": 100}
    for label in ("BULLISH", "BEARISH", "NEUTRAL"):
        for iv, regime in _REGIMES:
            c = fno.strategy_concept(label, iv, None, walls)
            assert c["iv_regime"] == regime
            for field in ("name", "note"):
                assert not _BANNED.search(c[field]), f"{label}/{iv}: {c[field]!r}"


def test_structure_concept_legs_are_balanced_and_anchored():
    walls = {"call_wall": 110, "put_wall": 100}
    for label in ("BULLISH", "BEARISH", "NEUTRAL"):
        for iv, _ in _REGIMES:
            legs = fno.strategy_concept(label, iv, None, walls)["legs"]
            if not legs:                       # the calendar spans two expiries
                continue
            # Every structure is defined-risk: one long leg per short leg, and
            # every anchor resolves against the dict emitted beside them.
            assert sum(1 for l in legs if l["pos"] == "long") == len(legs) // 2
            assert sum(1 for l in legs if l["pos"] == "short") == len(legs) // 2
            for l in legs:
                assert l["anchor"] in ("call_wall", "put_wall")
                assert l["right"] in ("call", "put")
                assert isinstance(l["step"], int)


def test_calendar_concept_emits_no_legs_because_one_chain_cannot_price_it():
    c = fno.strategy_concept("NEUTRAL", 9.0, None, {"call_wall": 110, "put_wall": 100})
    assert c["name"] == "Calendar Spread" and c["legs"] == []


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"OK — {name}")
