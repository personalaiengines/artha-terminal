"""
ARTHA Terminal - every LLM call goes through the router, on free defaults

Three regressions this pins, all found by inventorying the prompt sites:

  1. Five services POSTed to a provider directly with a hardcoded model and
     their own retry ladder, so they died when that one provider was
     rate-limited even with four other tiers idle.
  2. config.py declared free-tier model defaults on AIConfig, then overrode
     them in Config.__init__ with paid literals that always won. Anyone who
     set only an OPENROUTER_API_KEY got billed for claude-sonnet-4.5.
  3. Two grounding contracts drifted apart. Only the conversational one was
     ever hardened, so the tool-loop deep dive kept answering without the
     rules that were added after live fabrication incidents.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

SERVICES = ["services/fno_narrative.py", "services/market_news.py",
            "services/market_events.py", "services/stock_analysis_llm.py",
            "services/breadth.py"]
ROOT = Path(__file__).parent.parent


def test_no_service_posts_to_a_provider_directly():
    offenders = []
    for rel in SERVICES:
        body = (ROOT / rel).read_text(encoding="utf-8")
        for host in ("integrate.api.nvidia.com", "openrouter.ai",
                     "api.sambanova.ai", "models.inference.ai.azure.com"):
            if host in body:
                offenders.append(f"{rel} -> {host}")
    assert not offenders, (
        "these bypass ModelRouter and lose tier fallback: " + ", ".join(offenders))


def test_services_route_through_the_shared_helper():
    for rel in SERVICES:
        body = (ROOT / rel).read_text(encoding="utf-8")
        assert "from agent.llm_client import complete" in body, f"{rel} not on the router"


def test_shipped_defaults_are_free_models():
    # No env override: what someone gets from a bare .env.example plus one key.
    for var in ("OPENROUTER_PRIMARY_MODEL", "OPENROUTER_FALLBACK_MODEL",
                "NVIDIA_FALLBACK_MODEL", "NVIDIA_BACKUP_MODEL"):
        os.environ.pop(var, None)

    from config import Config
    ai = Config().ai

    assert not ai.primary_model.startswith("anthropic/"), \
        "the default chain must not open on a paid model"
    assert "gemini" not in ai.fallback_model_1
    assert ":free" in ai.primary_model and ":free" in ai.fallback_model_1


def test_both_grounding_contracts_share_one_source():
    from agent.chat import _STYLE
    from agent.prompts import BASE_SYSTEM_PROMPT, COMPLIANCE, GROUNDING

    for name, prompt in (("_STYLE", _STYLE), ("BASE_SYSTEM_PROMPT", BASE_SYSTEM_PROMPT)):
        assert GROUNDING in prompt, f"{name} does not compose the shared grounding rules"
        assert COMPLIANCE in prompt, f"{name} does not compose the shared compliance block"

    # The rules that only existed on the conversational side, from real
    # incidents: a fabricated intraday range, and a close attributed to a
    # broker terminal that was never consulted.
    for phrase in ("traded in a range", "Kotak Neo"):
        assert phrase in BASE_SYSTEM_PROMPT, \
            f"the deep-dive prompt lost the hard-won rule about {phrase!r}"


def test_tool_citation_rule_stays_out_of_the_chat_prompt():
    # The chat path has no tools to cite; demanding [Source: <tool>] there
    # would ask for annotations it cannot produce.
    from agent.chat import _STYLE
    from agent.prompts import BASE_SYSTEM_PROMPT

    assert "[Source:" in BASE_SYSTEM_PROMPT
    assert "[Source:" not in _STYLE


def test_complete_returns_empty_string_when_every_tier_fails(monkeypatch):
    # Callers treat "" as "no LLM available" and fall back to deterministic
    # output. It must never raise into a request handler.
    import agent.llm_client as lc

    async def boom(*_a, **_k):
        raise lc.AllTiersExhausted(["nvidia(x): 429", "openrouter(y): 429"])

    monkeypatch.setattr(lc.ModelRouter, "chat", boom)
    assert lc.complete("sys", "user") == ""


def test_complete_extracts_the_message_content(monkeypatch):
    import agent.llm_client as lc

    async def ok(_self, messages, tools=None, task_shape="deep"):
        assert messages[0]["role"] == "system" and messages[1]["role"] == "user"
        return {"choices": [{"message": {"content": "answer"}}]}

    monkeypatch.setattr(lc.ModelRouter, "chat", ok)
    assert lc.complete("sys", "user", task_shape="quick") == "answer"


def test_complete_survives_a_malformed_response(monkeypatch):
    import agent.llm_client as lc

    async def weird(*_a, **_k):
        return {"choices": []}

    monkeypatch.setattr(lc.ModelRouter, "chat", weird)
    assert lc.complete("sys", "user") == ""
