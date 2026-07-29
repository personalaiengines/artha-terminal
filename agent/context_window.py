"""
ARTHA Terminal - Sliding-window context compression

Keeps LLM requests routed to small-context free tiers (SambaNova's ~8K
ceiling) under budget by dropping older turns down to a single summary once
the crude token estimate exceeds the ceiling. The system prompt and the most
recent turns are always kept verbatim — those are what the model needs to
answer the current question; older turns matter far less.

Token counting here is deliberately approximate (len(text) // 4, the common
rule-of-thumb for English text) rather than pulling in `tiktoken` — this is a
routing/budget signal, not an exact accounting requirement, and the tier
ceilings themselves are provider-approximate too (see config.py).
"""

from __future__ import annotations


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _message_tokens(msg: dict) -> int:
    return _estimate_tokens(str(msg.get("content") or ""))


def compress_for_tier(messages: list[dict], max_tokens: int, keep_recent: int = 4) -> list[dict]:
    """Return `messages` unchanged if it already fits `max_tokens`. Otherwise
    keep the system prompt (if present) and the most recent `keep_recent`
    turns verbatim, and collapse everything older into one summary message.
    """
    total = sum(_message_tokens(m) for m in messages)
    if total <= max_tokens:
        return messages

    system = [m for m in messages if m.get("role") == "system"]
    rest = [m for m in messages if m.get("role") != "system"]

    recent = rest[-keep_recent:] if keep_recent > 0 else list(rest)
    older = rest[:-keep_recent] if keep_recent > 0 else []

    if not older:
        return messages  # nothing to drop — already at the floor

    summary_lines = []
    for m in older:
        role = m.get("role", "user")
        content = str(m.get("content") or "")[:200]
        if content:
            summary_lines.append(f"[{role}] {content}")
    summary_msg = {
        "role": "system",
        "content": "Earlier context (summarized to fit the context window):\n" + "\n".join(summary_lines),
    }

    return system + [summary_msg] + recent
