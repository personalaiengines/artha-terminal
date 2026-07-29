"""
ARTHA Terminal - Sliding-window context compression tests
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.context_window import compress_for_tier, _estimate_tokens


def test_under_budget_returned_unchanged():
    messages = [
        {"role": "system", "content": "You are ARTHA."},
        {"role": "user", "content": "Quick question."},
    ]
    assert compress_for_tier(messages, max_tokens=1000) is messages


def test_over_budget_keeps_system_and_recent_collapses_older():
    system = {"role": "system", "content": "You are ARTHA."}
    older = [{"role": "user", "content": "x" * 400} for _ in range(10)]
    recent = [{"role": "user", "content": "the current question"}]
    messages = [system] + older + recent

    out = compress_for_tier(messages, max_tokens=50, keep_recent=1)

    assert out[0] == system
    assert out[-1] == recent[0]
    # older turns collapsed into exactly one summary message in between
    assert len(out) == 3
    assert "summarized" in out[1]["content"].lower()


def test_compression_reduces_total_estimated_tokens():
    system = {"role": "system", "content": "sys"}
    older = [{"role": "user", "content": "y" * 1000} for _ in range(20)]
    recent = [{"role": "user", "content": "z"}]
    messages = [system] + older + recent

    before = sum(_estimate_tokens(str(m["content"])) for m in messages)
    out = compress_for_tier(messages, max_tokens=50, keep_recent=1)
    after = sum(_estimate_tokens(str(m["content"])) for m in out)

    assert after < before
