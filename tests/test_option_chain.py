"""Parser check for the Upstox option-chain normaliser (offline, no token)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.upstox import _parse_option_chain

# Minimal shape mirroring Upstox /v2/option/chain `data` rows (unsorted on purpose).
_SAMPLE = [
    {
        "strike_price": 22100,
        "underlying_spot_price": 22050.5,
        "call_options": {"market_data": {"ltp": 120.5, "oi": 1500, "prev_oi": 1000, "volume": 300},
                         "option_greeks": {"iv": 12.3, "delta": 0.55}},
        "put_options": {"market_data": {"ltp": 80.0, "oi": 900, "prev_oi": 1100, "volume": 250},
                        "option_greeks": {"iv": 13.1, "delta": -0.45}},
    },
    {
        "strike_price": 22000,
        "underlying_spot_price": 22050.5,
        "call_options": {"market_data": {"ltp": 180.0, "oi": 800, "prev_oi": 800, "volume": 500},
                         "option_greeks": {"iv": 11.9}},
        "put_options": {"market_data": {"ltp": 60.0, "oi": 2200, "prev_oi": 1500, "volume": 700},
                        "option_greeks": {"iv": 12.8}},
    },
]


def test_parse_option_chain():
    out = _parse_option_chain(_SAMPLE)

    assert out["spot"] == 22050.5
    # sorted ascending by strike
    assert [s["strike"] for s in out["strikes"]] == [22000, 22100]

    low, high = out["strikes"]
    # oi_change = oi - prev_oi
    assert high["call"]["oi_change"] == 500      # 1500 - 1000
    assert high["put"]["oi_change"] == -200      # 900 - 1100
    assert low["put"]["oi_change"] == 700        # 2200 - 1500
    # greeks / fields carried through
    assert high["call"]["iv"] == 12.3
    assert low["put"]["oi"] == 2200


def test_parse_handles_missing_and_empty():
    # empty input → empty, no crash
    assert _parse_option_chain([]) == {"spot": None, "strikes": []}
    # row missing greeks / prev_oi → None oi_change, no crash
    out = _parse_option_chain([
        {"strike_price": 100, "underlying_spot_price": 99,
         "call_options": {"market_data": {"ltp": 1.0, "oi": 10}},
         "put_options": {}},
    ])
    s = out["strikes"][0]
    assert s["call"]["oi_change"] is None        # prev_oi absent
    assert s["put"]["ltp"] is None               # whole leg absent
    assert out["spot"] == 99


def test_prev_close_gives_a_real_per_leg_price_change():
    # Upstox ships `close_price` (prior settled close) on every leg next to
    # `prev_oi` — verified live on NIFTY/BANKNIFTY/SENSEX, 100% coverage. That
    # is what makes the build-up quadrant a per-leg read, not an index proxy.
    out = _parse_option_chain([
        {"strike_price": 100, "underlying_spot_price": 99,
         "call_options": {"market_data": {"ltp": 12.0, "close_price": 10.0, "oi": 5, "prev_oi": 3},
                          "option_greeks": {"iv": 11.0, "delta": 0.6}},
         "put_options": {"market_data": {"ltp": 4.0, "close_price": 6.5, "oi": 8, "prev_oi": 9},
                         "option_greeks": {"iv": 12.0, "delta": -0.4}}},
    ])
    s = out["strikes"][0]
    assert s["call"]["prev_close"] == 10.0
    assert s["call"]["price_chg"] == 2.0         # 12.0 - 10.0
    assert s["put"]["price_chg"] == -2.5         # 4.0 - 6.5
    # no close_price → no change claimed
    bare = _parse_option_chain([
        {"strike_price": 100, "underlying_spot_price": 99,
         "call_options": {"market_data": {"ltp": 12.0}}, "put_options": {}},
    ])["strikes"][0]
    assert bare["call"]["prev_close"] is None and bare["call"]["price_chg"] is None


def test_a_greek_printed_as_literal_zero_is_reported_absent():
    # SENSEX's nearest expiry returns iv 0.0 / delta 0.0 on live ATM legs that
    # carry real OI. Zero is a thin-quote artifact, not a measurement (R17).
    out = _parse_option_chain([
        {"strike_price": 100, "underlying_spot_price": 99,
         "call_options": {"market_data": {"ltp": 12.0, "oi": 500},
                          "option_greeks": {"iv": 0.0, "delta": 0.0}},
         "put_options": {"market_data": {"ltp": 4.0, "oi": 500},
                         "option_greeks": {"iv": 12.0, "delta": -0.4}}},
    ])
    s = out["strikes"][0]
    assert s["call"]["iv"] is None and s["call"]["delta"] is None
    assert s["call"]["oi"] == 500                # the OI is real and survives
    assert s["put"]["delta"] == -0.4             # a genuine greek is untouched


if __name__ == "__main__":
    test_parse_option_chain()
    test_parse_handles_missing_and_empty()
    test_prev_close_gives_a_real_per_leg_price_change()
    test_a_greek_printed_as_literal_zero_is_reported_absent()
    print("OK — option-chain parser")
