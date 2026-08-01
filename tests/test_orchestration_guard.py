"""
ARTHA Terminal - zero-tool-call guard tests

agent/prompts.py orders the model to call a tool before stating any number
("You have no external knowledge"). A tool loop that returns prose on the very
first iteration, without calling a single tool, is therefore answering from
training data — and used to be returned as a SUCCESSFUL analysis and cached for
6h, indistinguishable from a grounded one.
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.orchestration import AgentOrchestrator

# Symbol nothing else caches, so a real dev-DB agent_cache row can't
# short-circuit analyze() before the tool loop runs.
_SYMBOL = "ZZGUARDTEST"


async def _toolless_prose(self, messages, tools=None, task_shape="deep"):
    """A model reply with content but no tool_calls — the failure being guarded."""
    return {
        "choices": [{"message": {
            "role": "assistant",
            "content": "RELIANCE trades around Rs 2,900 with a P/E near 25.",
        }}],
        "model": "some/free-model",
        "usage": {"total_tokens": 120},
    }


@pytest.mark.asyncio
async def test_zero_tool_call_answer_is_flagged_as_an_error():
    with patch("agent.llm_client.ModelRouter.chat", new=_toolless_prose):
        result = await AgentOrchestrator().analyze(_SYMBOL, use_cache=False)

    assert result["error"] == "no_tool_calls"
    assert result["tool_calls"] == []
    assert result["content"]  # kept for debugging, not discarded


@pytest.mark.asyncio
async def test_zero_tool_call_answer_is_never_cached():
    """The 6h TTL is the real damage: one ungrounded answer would be served to
    every later request for the same symbol, surviving a retry that would have
    succeeded."""
    with patch("agent.llm_client.ModelRouter.chat", new=_toolless_prose), \
            patch.object(AgentOrchestrator, "_set_cached") as set_cached:
        result = await AgentOrchestrator().analyze(_SYMBOL, use_cache=True)

    assert result["error"] == "no_tool_calls"
    set_cached.assert_not_called()
