"""
ARTHA Terminal - Debate layer (hand-rolled FinRobot-style Bull/Bear/Judge)

Why hand-rolled instead of vendoring FinRobot: FinRobot (AI4Finance-Foundation)
is an AutoGen/pyautogen research repo, not a maintained PyPI production
package — pulling it in would mean a second, competing agent-loop runtime
alongside the tool-use loop agent/orchestration.py already runs, plus a heavy
new dependency tree and glue to point AutoGen's LLM config at free tiers
instead of OpenAI/Azure. The substrate FinRobot would provide — several
system-prompted agents sharing a chat-completions client — already exists
here as ModelRouter.chat().

This does NOT re-fetch or recompute anything: scan_red_flags/compute_scorecard
were already called by the tool-use loop in agent/orchestration.py (an LLM
directed which tools to call, same as any other analysis) — extract_quant()
just pulls those results out of that loop's tool_calls log. The debate is
three additional "quick"-tier LLM calls that produce narrative ONLY. The
numeric score is copied straight from the engine's dict into the return value
and never round-tripped through any LLM's text output, so no prompt injection
or model misbehavior can silently change the number the user sees.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from agent.llm_client import ModelRouter

logger = logging.getLogger("agent.debate")

_BULL_SYSTEM = (
    "You are the Bull-case analyst in an internal research debate. Argue the "
    "strongest data-grounded case for a constructive read on this stock, using "
    "ONLY the quantitative findings provided below. Do not introduce any number "
    "not present in the findings. 2-4 concise bullet points."
)
_BEAR_SYSTEM = (
    "You are the Bear-case analyst in an internal research debate. Argue the "
    "strongest data-grounded case for caution on this stock, using ONLY the "
    "quantitative findings provided below. Do not introduce any number not "
    "present in the findings. 2-4 concise bullet points."
)
_JUDGE_SYSTEM = (
    "You are the Judge in an internal research debate. You have the "
    "quantitative findings and both the Bull and Bear arguments below. Write a "
    "balanced 2-3 sentence final verdict that weighs both sides. You may only "
    "contextualize or soften language — you cannot change any number or "
    "red-flag severity; the score shown to the user is taken directly from the "
    "findings, never from your text. End with a soft signal only "
    "(HOLD/WATCH/REVIEW) — never \"buy\" or \"sell\"."
)


def extract_quant(tool_calls: list[dict]) -> dict:
    """Pull the already-computed scan_red_flags/compute_scorecard results out
    of the tool-use loop's log. Never calls the tools itself."""
    red_flags = next((tc.get("result") for tc in tool_calls if tc.get("tool") == "scan_red_flags"), None)
    scorecard = next((tc.get("result") for tc in tool_calls if tc.get("tool") == "compute_scorecard"), None)
    return {"red_flags": red_flags, "scorecard": scorecard}


def _content(resp: dict) -> str:
    try:
        return resp["choices"][0]["message"]["content"] or ""
    except Exception:
        return ""


async def run_debate(symbol: str, quant: dict, draft: str) -> Optional[dict]:
    """Bull -> Bear -> Judge, each a 'quick'-tier call (short prompts, fast
    tier is the right fit — each role only needs the findings/draft, not the
    full historical snapshot). Returns None if there's no scorecard to anchor
    the debate to — nothing to debate without deterministic findings, and a
    debate manufactured without them would just be free-floating narrative."""
    scorecard = quant.get("scorecard") or {}
    if scorecard.get("status") == "NOT_FOUND" or scorecard.get("total_score") is None:
        return None

    findings_json = json.dumps(quant, default=str)
    router = ModelRouter()

    try:
        bull = await router.chat(
            [{"role": "system", "content": _BULL_SYSTEM},
             {"role": "user", "content": f"Symbol: {symbol}\n\nFindings:\n{findings_json}"}],
            task_shape="quick",
        )
        bear = await router.chat(
            [{"role": "system", "content": _BEAR_SYSTEM},
             {"role": "user", "content": f"Symbol: {symbol}\n\nFindings:\n{findings_json}"}],
            task_shape="quick",
        )
        bull_text, bear_text = _content(bull), _content(bear)

        judge = await router.chat(
            [{"role": "system", "content": _JUDGE_SYSTEM},
             {"role": "user", "content": (
                 f"Symbol: {symbol}\n\nFindings:\n{findings_json}\n\n"
                 f"Bull case:\n{bull_text}\n\nBear case:\n{bear_text}\n\n"
                 f"Existing draft analysis:\n{draft[:2000]}"
             )}],
            task_shape="quick",
        )
        verdict_text = _content(judge)
    except Exception as e:
        logger.warning(f"Debate failed for {symbol}: {e}")
        return None

    return {
        "bull": bull_text,
        "bear": bear_text,
        "verdict_text": verdict_text,
        # Copied straight from the engine's dict — never derived from any
        # LLM's text, so the debate can never silently change the number.
        "score": scorecard.get("total_score"),
    }
