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


if __name__ == "__main__":
    test_parse_option_chain()
    test_parse_handles_missing_and_empty()
    print("OK — option-chain parser")
