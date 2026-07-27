"""
ARTHA Terminal - Agent Console Component
Streams tool-use telemetry from the LLM agent to a side-rail panel.
"""

import streamlit as st
from datetime import datetime
from typing import Optional
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ui.theme import PALETTE, RGB


def render_agent_console(
    tool_calls: list,
    status: str = "idle",
    position: str = "side",  # 'side' or 'full'
) -> None:
    """
    Render the agent console panel with streamed tool calls.

    Args:
        tool_calls: List of tool-call telemetry dicts
        status: 'idle', 'running', 'complete', 'error'
        position: 'side' for a sidebar rail, 'full' for main column
    """
    container = st.sidebar if position == "side" else st.container()

    container.markdown(
        f"""
    <div style="background:{PALETTE['depth']}; border:1px solid {PALETTE['grid']};
                border-radius:10px; padding:0.5rem 0.75rem; font-size:0.75rem;
                margin-bottom:1rem;">
        <div style="color:{PALETTE['laser']}; font-weight:600;">Agent console</div>
    </div>
    """,
        unsafe_allow_html=True,
    )

    status_colors = {
        "idle": PALETTE["haze"],
        "running": PALETTE["laser"],
        "complete": PALETTE["surge"],
        "error": PALETTE["flare"],
    }

    status_color = status_colors.get(status, PALETTE["haze"])
    container.markdown(
        f"<div style='color:{status_color}; font-size:0.8rem; "
        f"padding:0.25rem 0.5rem; border:1px solid {status_color}; "
        f"border-radius:4px; margin-bottom:0.5rem; text-align:center;'>"
        f"{status.upper()}</div>",
        unsafe_allow_html=True,
    )

    # Stream tool call lines
    for call in tool_calls:
        timestamp = call.get("timestamp", "")
        tool_name = call.get("tool", "")
        call_type = call.get("type", "")
        args = call.get("args", {})

        if call_type == "tool_call":
            color = PALETTE["laser"]
            icon = "▶"
            text = f"{timestamp} {icon} {tool_name}({args})"
        elif call_type == "tool_result":
            color = PALETTE["surge"]
            icon = "✓"
            summary = str(call.get("result_summary", ""))[:60]
            text = f"{timestamp} {icon} {tool_name} → {summary}"
        elif call_type == "cache_hit":
            color = PALETTE["volt"]
            icon = "⚡"
            text = f"{timestamp} {icon} CACHE HIT"
        elif call_type == "analysis_start":
            color = PALETTE["laser"]
            icon = "🚀"
            text = f"{timestamp} {icon} START: {call.get('symbol')} / {call.get('analysis_type')}"
        elif call_type == "analysis_complete":
            color = PALETTE["surge"]
            icon = "✅"
            text = f"{timestamp} {icon} DONE: {call.get('tool_calls')} calls, {call.get('tokens')} tokens"
        else:
            color = PALETTE["haze"]
            icon = "•"
            text = f"{timestamp} {icon} {call_type}"

        container.markdown(
            f"<div style='padding:3px 6px; color:{color}; "
            f"border-bottom:1px solid rgba({RGB['grid']},0.35); "
            f"word-break:break-all; font-size:0.7rem;'>{text}</div>",
            unsafe_allow_html=True,
        )

    if not tool_calls:
        container.markdown(
            f"<div style='color:{PALETTE['haze']}; font-size:0.75rem; "
            f"padding:1rem; text-align:center;'>Console idle. Run a deep-dive to see tool calls.</div>",
            unsafe_allow_html=True,
        )


class AgentTelemetryCollector:
    """
    Collects telemetry from the agent loop for UI rendering.

    Usage:
        collector = AgentTelemetryCollector()
        # Pass collector.on_event as the on_tool_call callback
        result = await orchestrator.analyze(symbol, on_tool_call=collector.on_event)
        # Then render:
        render_agent_console(collector.events, status="complete")
    """

    def __init__(self):
        self.events: list[dict] = []
        self.status = "idle"

    async def on_event(self, event: dict) -> None:
        """Callback for the orchestrator to stream telemetry events."""
        import asyncio
        import datetime as dt

        event = event.copy()
        event["timestamp"] = dt.datetime.now().strftime("%H:%M:%S")
        self.events.append(event)

        if event.get("type") == "analysis_start":
            self.status = "running"
        elif event.get("type") == "analysis_complete":
            self.status = "complete"

        # Yield control to allow UI updates
        await asyncio.sleep(0)


def render_tool_call_summary(tool_calls: list) -> dict:
    """Summarize tool calls for a compact stat display."""
    summary = {
        "total_calls": len(tool_calls),
        "unique_tools": set(),
        "iterations": 0,
    }

    for call in tool_calls:
        if call.get("type") == "tool_call":
            summary["unique_tools"].add(call.get("tool"))

    summary["unique_tools"] = list(summary["unique_tools"])
    return summary


__all__ = [
    "render_agent_console",
    "AgentTelemetryCollector",
    "render_tool_call_summary",
]