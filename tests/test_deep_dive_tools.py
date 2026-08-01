"""
ARTHA Terminal - deep-dive tool coverage

The deep-dive loop (agent/orchestration.py) can only ever see what
agent/tools.py registers, and the model only calls what DEEP_DIVE_PROMPT names.
Two live signals used to sit one file away and be structurally invisible to it:
market-wide FII/DII flows (services/institutional_flows.py, already feeding the
chat path) and index membership (the index_members table, already feeding
screen_facts). A verdict that never states either is the user's "no holistic
view" complaint, exactly.

So: registry and schema list must agree, and both new tools must be named in the
prompt. A tool the prompt never mentions does not get called.
"""

import asyncio

import pytest

from agent import tools
from agent.prompts import DEEP_DIVE_PROMPT


NEW_TOOLS = ("get_institutional_flows", "get_index_membership")


def test_registry_and_schemas_agree():
    schema_names = {s["function"]["name"] for s in tools.TOOL_SCHEMAS}
    assert schema_names == set(tools.registry._tools), (
        "a tool registered without a schema is never offered to the model; "
        "a schema without a handler is an 'Unknown tool' error mid-analysis"
    )


@pytest.mark.parametrize("name", NEW_TOOLS)
def test_new_tools_are_registered_and_exposed(name):
    assert tools.registry.get_tool(name) is not None
    assert name in {s["function"]["name"] for s in tools.get_tools_for_llm()}


@pytest.mark.parametrize("name", NEW_TOOLS)
def test_deep_dive_prompt_names_the_new_tools(name):
    assert name in DEEP_DIVE_PROMPT


def test_synthesis_is_required_to_state_flows_and_membership():
    # Not enough to list the tools — the output sections must demand the answer.
    assert "MARKET CONTEXT" in DEEP_DIVE_PROMPT
    assert "[Source: get_institutional_flows]" in DEEP_DIVE_PROMPT
    assert "[Source: get_index_membership]" in DEEP_DIVE_PROMPT


# --- shapes -----------------------------------------------------------

@pytest.mark.needs_data
def test_index_membership_for_a_symbol_with_data():
    # RELIANCE is in the repo's dev DB index_members (NIFTY 50 et al). Assert the
    # shape, not which indices — membership comes from the weekly NSE pull.
    res = asyncio.run(tools.get_index_membership("reliance"))
    assert res["symbol"] == "RELIANCE"
    assert res["available"] is True and res["status"] == "OK"
    assert res["indices"], "expected at least one stored index membership"
    for row in res["indices"]:
        assert set(row) == {"index_key", "index_name", "industry"}


def test_index_membership_for_a_symbol_without_data():
    # No index, no invention: the tool says so and tells the model to say so.
    res = asyncio.run(tools.get_index_membership("NOSUCHSYMBOL"))
    assert res["available"] is False
    assert res["indices"] == []
    assert res["status"] == "NOT_FOUND"
    assert "not" in res["message"].lower()


def test_institutional_flows_reports_a_direction_or_says_unavailable(monkeypatch):
    tools._snap_cache.pop(tools._FLOWS_KEY, None)
    import services.institutional_flows as flows

    monkeypatch.setattr(flows, "get_institutional_snapshot", lambda: {
        "date": "30-Jul-2026",
        "fii": {"buy": 1.0, "sell": 2.0, "net": -1250.5},
        "dii": {"buy": 3.0, "sell": 1.0, "net": 980.25},
        "fii_key": "bearish", "dii_key": "bullish", "stale": False,
        "trend": {"fii_streak": -3, "dii_streak": 4, "fii_sum": -4000.0, "dii_sum": 5000.0},
    })
    res = asyncio.run(tools.get_institutional_flows())
    assert res["available"] is True and res["status"] == "OK"
    assert res["fii_net"] == -1250.5 and res["fii_stance"] == "bearish"
    assert res["dii_net"] == 980.25 and res["dii_stance"] == "bullish"
    assert res["date"] == "30-Jul-2026" and res["stale"] is False
    assert res["fii_streak_days"] == -3 and res["dii_sum_10d"] == 5000.0

    # NSE publishes this once a day and the fetch does fail. An absent reading
    # must not read as a neutral one.
    tools._snap_cache.pop(tools._FLOWS_KEY, None)
    monkeypatch.setattr(flows, "get_institutional_snapshot", dict)
    res = asyncio.run(tools.get_institutional_flows())
    assert res["available"] is False
    assert res["status"] == "NOT_FOUND"
    assert "unavailable" in res["message"].lower()
    tools._snap_cache.pop(tools._FLOWS_KEY, None)
