"""
ARTHA Terminal - breadth ratio scale

The adv/dec ratio is plotted on a log-spaced 0-1 scale so the marker sits in a
judgeable place: parity must land dead centre, not at 1/3 of the track (which
is where a linear 0-3 scale would put it, making an even market look bearish).

Mirrors ratioPos() in web/components/widgets/market-breadth.tsx.
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def ratio_pos(r: float) -> float:
    if not math.isfinite(r) or r <= 0:
        return 0.0
    clamped = min(3.0, max(1 / 3, r))
    return (math.log(clamped) - math.log(1 / 3)) / (math.log(3) - math.log(1 / 3))


def test_parity_sits_in_the_middle():
    assert ratio_pos(1.0) == 0.5


def test_symmetric_around_parity():
    # 2x as many advancers should sit as far right of centre as 2x as many
    # decliners sits left of it.
    assert abs((ratio_pos(2.0) - 0.5) + (ratio_pos(0.5) - 0.5)) < 1e-9


def test_clamped_to_the_track():
    assert ratio_pos(50.0) == 1.0
    assert ratio_pos(0.01) == 0.0
    assert ratio_pos(float("inf")) == 0.0   # rendered as the ∞ label instead


def test_monotonic():
    vals = [ratio_pos(r) for r in (0.4, 0.8, 1.0, 1.5, 2.5)]
    assert vals == sorted(vals)
