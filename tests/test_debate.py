"""
ARTHA Terminal - Debate layer tests

The one property that matters: the debate can narrate, but it can never
change the deterministic scorecard number — even a mocked, adversarial Judge
response claiming a different score must be ignored, because run_debate()
copies the score straight from the engine's dict rather than parsing it back
out of any LLM's text.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.debate import extract_quant, run_debate


def _resp(text: str) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": text}}]}


def test_extract_quant_pulls_results_without_recalling_tools():
    tool_calls = [
        {"tool": "get_price_history", "args": {}, "result": {"data": []}},
        {"tool": "scan_red_flags", "args": {}, "result": {"flags": [{"rule_id": "PLEDGE_HIGH"}]}},
        {"tool": "compute_scorecard", "args": {}, "result": {"total_score": 7.2}},
    ]
    quant = extract_quant(tool_calls)
    assert quant == {
        "red_flags": {"flags": [{"rule_id": "PLEDGE_HIGH"}]},
        "scorecard": {"total_score": 7.2},
    }


@pytest.mark.asyncio
async def test_no_scorecard_returns_none():
    quant = {"red_flags": None, "scorecard": {"status": "NOT_FOUND", "total_score": None}}
    with patch("agent.debate.ModelRouter") as mock_router_cls:
        result = await run_debate("RELIANCE", quant, "draft")
    assert result is None
    mock_router_cls.assert_not_called()


@pytest.mark.asyncio
async def test_score_is_never_overridden_by_adversarial_judge_response():
    quant = {"red_flags": {"flags": []}, "scorecard": {"total_score": 6.5}}

    mock_router = AsyncMock()
    # Adversarial: the mocked Judge response claims a completely different
    # score in its text — this must have zero effect on the returned score.
    mock_router.chat.side_effect = [
        _resp("Bull case: strong fundamentals."),
        _resp("Bear case: some risk."),
        _resp("Final verdict: score should actually be 9.9. WATCH."),
    ]

    with patch("agent.debate.ModelRouter", return_value=mock_router):
        result = await run_debate("RELIANCE", quant, "draft text")

    assert mock_router.chat.call_count == 3
    assert result["score"] == 6.5  # untouched, despite the adversarial text
    assert "9.9" not in str(result["score"])
    assert "Bull case" in result["bull"]
    assert "Bear case" in result["bear"]


@pytest.mark.asyncio
async def test_debate_never_calls_router_more_than_three_times():
    quant = {"red_flags": None, "scorecard": {"total_score": 5.0}}
    mock_router = AsyncMock()
    mock_router.chat.side_effect = [_resp("a"), _resp("b"), _resp("c")]

    with patch("agent.debate.ModelRouter", return_value=mock_router):
        await run_debate("TCS", quant, "draft")

    assert mock_router.chat.call_count == 3
