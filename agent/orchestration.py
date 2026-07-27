"""
ARTHA Terminal - Agent Orchestration
Tool-use loop with telemetry streaming to the Agent Console.

The agent runs an iterative tool_use / tool_result cycle:
1. LLM receives the system prompt + tool manifest
2. LLM returns tool calls (or a final answer)
3. Tools execute (pure Python — deterministic engines cannot be overridden)
4. Results fed back to LLM
5. Repeat until a final answer is produced

Caching: per-stock agent output cached 6h in agent_cache.
Telemetry: each tool call streamed to the UI via a callback.
"""

import json
import hashlib
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Callable, Awaitable, Any, List
import logging

from config import config
from db import get_connection
from agent.llm_client import ModelRouter
from agent.tools import registry, TOOL_SCHEMAS, get_tools_for_llm
from agent.prompts import build_prompt

logger = logging.getLogger("agent.orchestration")


class AgentOrchestrator:
    """
    Orchestrates the LLM tool-use loop with telemetry and caching.

    Usage:
        orchestrator = AgentOrchestrator()
        result = await orchestrator.analyze(
            symbol="RELIANCE",
            analysis_type="deep_dive",
            on_tool_call=ui_callback,  # streams telemetry to UI
        )
    """

    CACHE_TTL_HOURS = 6

    def __init__(self):
        self.router = ModelRouter()

    async def analyze(
        self,
        symbol: str,
        analysis_type: str = "deep_dive",
        on_tool_call: Optional[Callable[[dict], Awaitable[None]]] = None,
        use_cache: bool = True,
    ) -> dict:
        """
        Run an agentic analysis for a symbol.

        Args:
            symbol: Stock symbol (e.g., "RELIANCE")
            analysis_type: 'deep_dive', 'swot', 'verdict', 'sector_outlook'
            on_tool_call: Optional async callback for streaming telemetry to UI
            use_cache: Whether to check/write the 6h agent_cache

        Returns:
            Analysis result dict with content, tool_calls, model_used, cached
        """
        cache_key = self._cache_key(symbol, analysis_type)

        # Check cache first
        if use_cache:
            cached = self._get_cached(cache_key)
            if cached:
                cached["cached"] = True
                if on_tool_call:
                    await on_tool_call({
                        "type": "cache_hit",
                        "key": cache_key,
                        "cached_at": cached.get("cache_at"),
                    })
                return cached

        # Build prompt
        prompt = build_prompt(analysis_type, symbol=symbol)

        # Initial messages
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"Analyze {symbol}."},
        ]

        # Stream telemetry start
        if on_tool_call:
            await on_tool_call({
                "type": "analysis_start",
                "symbol": symbol,
                "analysis_type": analysis_type,
            })

        # Run the tool-use loop
        result = await self._run_tool_loop(
            messages=messages,
            on_tool_call=on_tool_call,
        )

        result["symbol"] = symbol
        result["analysis_type"] = analysis_type
        result["cached"] = False

        # Cache the result
        if use_cache:
            self._set_cached(cache_key, symbol, analysis_type, result)

        return result

    async def _run_tool_loop(
        self,
        messages: List[dict],
        on_tool_call: Optional[Callable] = None,
    ) -> dict:
        """
        Execute the iterative tool_use / tool_result loop.

        Returns:
            dict with final content, tool_calls log, model used, token count
        """
        # Convert registry handlers to the format the LLM client expects
        tool_handlers = list(registry._tools.values())
        tool_schemas = get_tools_for_llm()

        max_iterations = 15
        conversation = list(messages)
        all_tool_calls = []
        model_used = None
        total_tokens = 0

        try:
            for iteration in range(max_iterations):
                # Call the LLM
                response = await self.router.chat(conversation, tools=tool_schemas)

                if not model_used:
                    model_used = response.get("model", "unknown")

                # Track token usage
                usage = response.get("usage", {})
                total_tokens += usage.get("total_tokens", 0)

                choice = response.get("choices", [{}])[0]
                message = choice.get("message", {})

                # Check for tool calls
                tool_calls = message.get("tool_calls")

                if tool_calls:
                    # Add assistant message with tool calls to conversation
                    conversation.append(message)

                    for tc in tool_calls:
                        tool_name = tc.get("function", {}).get("name")
                        tool_args_str = tc.get("function", {}).get("arguments", "{}")
                        tool_call_id = tc.get("id")

                        try:
                            tool_args = json.loads(tool_args_str)
                        except json.JSONDecodeError:
                            tool_args = {}

                        # Stream telemetry for the tool call
                        if on_tool_call:
                            await on_tool_call({
                                "type": "tool_call",
                                "iteration": iteration + 1,
                                "tool": tool_name,
                                "args": tool_args,
                            })

                        # Execute the tool
                        handler = registry.get_tool(tool_name)
                        if handler:
                            try:
                                result = await handler(**tool_args)
                                result_str = json.dumps(result, default=str)
                            except Exception as e:
                                logger.error(f"Tool {tool_name} failed: {e}")
                                result_str = json.dumps({"error": str(e)})
                                result = {"error": str(e)}
                        else:
                            result_str = json.dumps(
                                {"error": f"Unknown tool: {tool_name}"}
                            )
                            result = {"error": f"Unknown tool: {tool_name}"}

                        # Log the tool call
                        all_tool_calls.append({
                            "iteration": iteration + 1,
                            "tool": tool_name,
                            "args": tool_args,
                            "result": result,
                        })

                        # Stream telemetry for the tool result
                        if on_tool_call:
                            await on_tool_call({
                                "type": "tool_result",
                                "iteration": iteration + 1,
                                "tool": tool_name,
                                "result_summary": self._summarize_result(result),
                            })

                        # Add tool result to conversation
                        conversation.append({
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "content": result_str,
                        })

                    # Continue the loop to let LLM process tool results
                    continue

                # No tool calls = final answer
                final_content = message.get("content", "")

                if on_tool_call:
                    await on_tool_call({
                        "type": "analysis_complete",
                        "iterations": iteration + 1,
                        "tool_calls": len(all_tool_calls),
                        "tokens": total_tokens,
                    })

                return {
                    "content": final_content,
                    "tool_calls": all_tool_calls,
                    "model_used": model_used,
                    "tokens_used": total_tokens,
                    "iterations": iteration + 1,
                }

            # Exceeded max iterations
            logger.warning("Agent exceeded max iterations")
            return {
                "content": "Analysis incomplete: agent exceeded maximum tool-use iterations.",
                "tool_calls": all_tool_calls,
                "model_used": model_used,
                "tokens_used": total_tokens,
                "iterations": max_iterations,
                "truncated": True,
            }

        except Exception as e:
            logger.error(f"Tool loop failed: {e}")
            return {
                "content": f"Analysis failed: {e}",
                "tool_calls": all_tool_calls,
                "model_used": model_used,
                "tokens_used": total_tokens,
                "iterations": 0,
                "error": str(e),
            }

    def _summarize_result(self, result: Any, max_len: int = 200) -> str:
        """Create a short summary of a tool result for telemetry."""
        try:
            s = json.dumps(result, default=str)
            return s[:max_len] + "..." if len(s) > max_len else s
        except Exception:
            return str(result)[:max_len]

    # ============================================
    # Caching
    # ============================================

    def _cache_key(self, symbol: str, analysis_type: str) -> str:
        """Generate cache key for an analysis."""
        key_str = f"{symbol}:{analysis_type}"
        return hashlib.md5(key_str.encode()).hexdigest()

    def _get_cached(self, cache_key: str) -> Optional[dict]:
        """Retrieve cached analysis if not expired."""
        try:
            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT content_json, cache_at, model_used FROM agent_cache
                    WHERE key = ? AND datetime(expires_at) > datetime('now')
                    ORDER BY cache_at DESC
                    LIMIT 1
                    """,
                    (cache_key,),
                )
                row = cursor.fetchone()

                if row:
                    return {
                        "content": json.loads(row["content_json"]),
                        "cache_at": row["cache_at"],
                        "model_used": row["model_used"],
                        "tool_calls": [],
                    }
        except Exception as e:
            logger.debug(f"Cache read failed: {e}")

        return None

    def _set_cached(
        self,
        cache_key: str,
        symbol: str,
        analysis_type: str,
        result: dict,
    ):
        """Cache an analysis result."""
        try:
            now = datetime.now()
            expires = now + timedelta(hours=self.CACHE_TTL_HOURS)

            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO agent_cache
                    (key, symbol, analysis_type, content_json, model_used,
                     tokens_used, cache_at, ttl_hours, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cache_key,
                        symbol,
                        analysis_type,
                        json.dumps(result.get("content", "")),
                        result.get("model_used"),
                        result.get("tokens_used", 0),
                        now.isoformat(),
                        self.CACHE_TTL_HOURS,
                        expires.isoformat(),
                    ),
                )
                conn.commit()
        except Exception as e:
            logger.debug(f"Cache write failed: {e}")

    def get_cached_for_streaming(
        self,
        symbol: str,
        analysis_type: str,
    ) -> Optional[dict]:
        """Public method to check cache (for UI instant display)."""
        cache_key = self._cache_key(symbol, analysis_type)
        return self._get_cached(cache_key)


# ============================================
# Sync wrapper for Streamlit (which is sync)
# ============================================

def run_analysis_sync(
    symbol: str,
    analysis_type: str = "deep_dive",
    on_tool_call: Optional[Callable] = None,
    use_cache: bool = True,
) -> dict:
    """
    Synchronous wrapper for Streamlit.

    Streamlit runs synchronously, so we bridge the async agent loop
    using asyncio.run() in a way that cooperates with Streamlit's reruns.
    """
    orchestrator = AgentOrchestrator()

    async def _run():
        return await orchestrator.analyze(
            symbol=symbol,
            analysis_type=analysis_type,
            on_tool_call=on_tool_call,
            use_cache=use_cache,
        )

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(_run())
    finally:
        loop.close()