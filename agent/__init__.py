"""
ARTHA Terminal - Agent Module
LLM orchestration and tool-use loop.
"""

from .llm_client import LLMClient, OpenRouterClient, NvidiaNIMClient, ModelRouter
from .tools import Tool, ToolRegistry, registry, get_tools_for_llm
from .orchestration import AgentOrchestrator, run_analysis_sync
from .prompts import build_prompt

__all__ = [
    "LLMClient",
    "OpenRouterClient",
    "NvidiaNIMClient",
    "ModelRouter",
    "Tool",
    "ToolRegistry",
    "registry",
    "get_tools_for_llm",
    "AgentOrchestrator",
    "run_analysis_sync",
    "build_prompt",
]