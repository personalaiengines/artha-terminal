"""
ARTHA Terminal - Agent LLM Client
OpenRouter and Nvidia NIM API support with automatic fallback.
"""

import httpx
import json
from abc import ABC, abstractmethod
from typing import Optional, Callable
import os

from config import config


class LLMClient(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    async def chat(self, messages: list, tools: list = None) -> dict:
        """Send chat request and get response."""
        pass

    @abstractmethod
    async def tool_use_loop(self, messages: list, tools: list[Callable]) -> tuple[str, list]:
        """Run iterative tool-use loop until final answer."""
        pass


class OpenRouterClient(LLMClient):
    """OpenRouter API client (free-tier model, e.g. Nemotron/Llama, via a single endpoint)."""

    def __init__(self):
        self.base_url = "https://openrouter.ai/api/v1/chat/completions"
        self.api_key = config.ai.openrouter_api_key
        self.primary_model = config.ai.primary_model
        self.fallback_model = config.ai.fallback_model_1
        self._current_model = self.primary_model

    async def chat(self, messages: list, tools: list = None) -> dict:
        """Send chat request to OpenRouter."""
        if not self.api_key:
            raise ValueError("OpenRouter API key not configured")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://artha.local",
            "X-Title": "ARTHA Terminal",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self._current_model,
            "messages": messages,
            "tool_choice": "auto" if tools else None,
        }

        if tools:
            payload["tools"] = tools

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(self.base_url, headers=headers, json=payload)

            if response.status_code == 401:
                raise ValueError("OpenRouter API key invalid or exhausted")

            response.raise_for_status()
            return response.json()

    async def tool_use_loop(
        self, messages: list, tools: list[Callable]
    ) -> tuple[str, list]:
        """Iterative tool-use loop with automatic chat completion."""
        tool_registry = {t.__name__: t for t in tools}

        max_iterations = 10
        conversation = list(messages)
        tool_calls_log = []

        for _ in range(max_iterations):
            response = await self.chat(conversation, tools=list(tool_registry.keys()))

            choice = response["choices"][0]
            message = choice["message"]

            # Check for tool calls
            if "tool_calls" in message and message["tool_calls"]:
                for tc in message["tool_calls"]:
                    tool_name = tc["function"]["name"]
                    tool_args = json.loads(tc["function"]["arguments"])

                    # Add assistant's tool call to conversation
                    conversation.append(message)

                    if tool_name in tool_registry:
                        try:
                            result = await tool_registry[tool_name](**tool_args)
                            tool_calls_log.append({
                                "tool": tool_name,
                                "args": tool_args,
                                "result": result,
                            })

                            # Add tool result to conversation
                            conversation.append({
                                "role": "tool",
                                "tool_call_id": tc["id"],
                                "content": json.dumps(result),
                            })
                        except Exception as e:
                            conversation.append({
                                "role": "tool",
                                "tool_call_id": tc["id"],
                                "content": f"Error: {str(e)}",
                            })
                    else:
                        conversation.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": f"Unknown tool: {tool_name}",
                        })
                continue  # Continue loop to process tool results

            # Final answer
            return message.get("content", ""), tool_calls_log

        raise RuntimeError("Max tool-use iterations exceeded")


class AnthropicClient(LLMClient):
    """Direct Anthropic Messages API client — OPTIONAL, PAID, off by default.

    Only used when ANTHROPIC_API_KEY is explicitly set; ModelRouter skips this
    entirely otherwise and runs the free OpenRouter/NIM chain. Exists so a
    specific use-case can opt into paying for Claude without changing the
    default free stack everything else runs on.

    Bridges the OpenAI-chat-completions shape the rest of the agent speaks
    (messages/tool_calls dicts, {"choices":[{"message":...}]} responses) to the
    Anthropic Messages API on the way in and out, so orchestration.py's tool
    loop and api/server.py's free-form chat path need no changes.
    """

    def __init__(self):
        self.api_key = config.ai.anthropic_api_key
        self.model = config.ai.anthropic_model
        self._client = None

    def _sdk(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.AsyncAnthropic(api_key=self.api_key)
        return self._client

    @staticmethod
    def _to_anthropic_tools(tools: list | None) -> list[dict] | None:
        if not tools:
            return None
        out = []
        for t in tools:
            fn = t.get("function", t) if isinstance(t, dict) else None
            if not fn:
                continue
            out.append({
                "name": fn["name"],
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
            })
        return out or None

    @staticmethod
    def _to_anthropic_messages(messages: list) -> tuple[str, list[dict]]:
        """Split OpenAI-style messages into (system_text, anthropic_messages)."""
        system_parts = []
        out = []
        for m in messages:
            role = m.get("role")
            if role == "system":
                if m.get("content"):
                    system_parts.append(m["content"])
            elif role == "user":
                out.append({"role": "user", "content": m.get("content") or ""})
            elif role == "assistant":
                content = []
                if m.get("content"):
                    content.append({"type": "text", "text": m["content"]})
                for tc in (m.get("tool_calls") or []):
                    fn = tc.get("function", {})
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except (json.JSONDecodeError, TypeError):
                        args = {}
                    content.append({
                        "type": "tool_use", "id": tc.get("id"),
                        "name": fn.get("name"), "input": args,
                    })
                out.append({"role": "assistant", "content": content or [{"type": "text", "text": ""}]})
            elif role == "tool":
                out.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": m.get("tool_call_id"),
                        "content": str(m.get("content") or ""),
                    }],
                })
        return "\n\n".join(system_parts), out

    @staticmethod
    def _from_anthropic_response(resp) -> dict:
        """Convert an Anthropic Message into the {"choices": [...]} shape the
        rest of the agent expects."""
        text_parts, tool_calls = [], []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append({
                    "id": block.id, "type": "function",
                    "function": {"name": block.name, "arguments": json.dumps(block.input)},
                })
        message = {"role": "assistant", "content": "\n".join(text_parts) or None}
        if tool_calls:
            message["tool_calls"] = tool_calls
        usage = getattr(resp, "usage", None)
        total = (getattr(usage, "input_tokens", 0) or 0) + (getattr(usage, "output_tokens", 0) or 0)
        return {"choices": [{"message": message}], "model": resp.model,
                "usage": {"total_tokens": total}}

    async def chat(self, messages: list, tools: list = None) -> dict:
        if not self.api_key:
            raise ValueError("Anthropic API key not configured")

        system_text, anth_messages = self._to_anthropic_messages(messages)
        anth_tools = self._to_anthropic_tools(tools)

        kwargs = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": anth_messages,
            "thinking": {"type": "adaptive"},
        }
        if system_text:
            kwargs["system"] = system_text
        if anth_tools:
            kwargs["tools"] = anth_tools

        resp = await self._sdk().messages.create(**kwargs)
        return self._from_anthropic_response(resp)

    async def tool_use_loop(self, messages: list, tools: list[Callable]) -> tuple[str, list]:
        """Iterative tool-use loop (same contract as the other clients)."""
        tool_registry = {t.__name__: t for t in tools}
        max_iterations = 10
        conversation = list(messages)
        tool_calls_log = []

        for _ in range(max_iterations):
            response = await self.chat(conversation, tools=list(tool_registry.keys()))
            message = response["choices"][0]["message"]

            if message.get("tool_calls"):
                conversation.append(message)
                for tc in message["tool_calls"]:
                    tool_name = tc["function"]["name"]
                    tool_args = json.loads(tc["function"]["arguments"])
                    if tool_name in tool_registry:
                        try:
                            result = await tool_registry[tool_name](**tool_args)
                            tool_calls_log.append({"tool": tool_name, "args": tool_args, "result": result})
                            conversation.append({"role": "tool", "tool_call_id": tc["id"], "content": json.dumps(result)})
                        except Exception as e:
                            conversation.append({"role": "tool", "tool_call_id": tc["id"], "content": f"Error: {str(e)}"})
                    else:
                        conversation.append({"role": "tool", "tool_call_id": tc["id"], "content": f"Unknown tool: {tool_name}"})
                continue

            return message.get("content", ""), tool_calls_log

        raise RuntimeError("Max tool-use iterations exceeded")


class NvidiaNIMClient(LLMClient):
    """Nvidia NIM API client (fallback when OpenRouter exhausted)."""

    def __init__(self):
        self.base_url = "https://integrate.api.nvidia.com/v1/chat/completions"
        self.api_key = config.ai.nvidia_api_key
        self.model = config.ai.fallback_model_2

    async def chat(self, messages: list, tools: list = None) -> dict:
        """Send chat request to Nvidia NIM."""
        if not self.api_key:
            raise ValueError("Nvidia NIM API key not configured")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "messages": messages,
            "tool_choice": "auto" if tools else None,
        }

        if tools:
            payload["tools"] = tools

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(self.base_url, headers=headers, json=payload)
            response.raise_for_status()
            return response.json()

    async def tool_use_loop(
        self, messages: list, tools: list[Callable]
    ) -> tuple[str, list]:
        """Iterative tool-use loop (same logic as OpenRouter)."""
        tool_registry = {t.__name__: t for t in tools}

        max_iterations = 10
        conversation = list(messages)
        tool_calls_log = []

        for _ in range(max_iterations):
            response = await self.chat(conversation, tools=list(tool_registry.keys()))

            choice = response["choices"][0]
            message = choice["message"]

            if "tool_calls" in message and message["tool_calls"]:
                for tc in message["tool_calls"]:
                    tool_name = tc["function"]["name"]
                    tool_args = json.loads(tc["function"]["arguments"])

                    conversation.append(message)

                    if tool_name in tool_registry:
                        try:
                            result = await tool_registry[tool_name](**tool_args)
                            tool_calls_log.append({
                                "tool": tool_name,
                                "args": tool_args,
                                "result": result,
                            })
                            conversation.append({
                                "role": "tool",
                                "tool_call_id": tc["id"],
                                "content": json.dumps(result),
                            })
                        except Exception as e:
                            conversation.append({
                                "role": "tool",
                                "tool_call_id": tc["id"],
                                "content": f"Error: {str(e)}",
                            })
                continue

            return message.get("content", ""), tool_calls_log

        raise RuntimeError("Max tool-use iterations exceeded")


class ModelRouter:
    """Automatic fallback router between LLM providers."""

    def __init__(self):
        self.anthropic = AnthropicClient()
        self.openrouter = OpenRouterClient()
        self.nvidia = NvidiaNIMClient()
        self.model_chain = config.ai.get_model_chain()
        self._current_index = 0

    async def chat(self, messages: list, tools: list = None) -> dict:
        """Direct Anthropic first (when configured), then OpenRouter/NIM chain."""
        if self.anthropic.api_key:
            try:
                return await self.anthropic.chat(messages, tools)
            except Exception as e:
                print(f"[warn] Anthropic failed ({self.anthropic.model}): {e}; falling back")

        for i in range(len(self.model_chain)):
            try:
                if i == 0 or i == 1:  # OpenRouter models
                    client = self.openrouter
                    if i == 0:
                        client._current_model = self.model_chain[0]
                    else:
                        client._current_model = self.model_chain[1]
                else:  # Nvidia models
                    client = self.nvidia
                    if i == 2:
                        client.model = self.model_chain[2]
                    else:
                        client.model = self.model_chain[3]

                return await client.chat(messages, tools)

            except Exception as e:
                print(f"[warn] Provider failed ({self.model_chain[i]}): {e}")
                continue

        raise RuntimeError("All LLM providers failed")

    async def tool_use_loop(
        self, messages: list, tools: list[Callable]
    ) -> tuple[str, list]:
        """Try direct Anthropic first, then OpenRouter, then NIM on any failure
        (402, rate limit, …).

        Previously OpenRouter-only: if it errored (e.g. no credits) the agent never
        reached the free NIM tier. Now NIM is a real fallback for every OpenRouter call.
        """
        errors = []
        if self.anthropic.api_key:
            try:
                return await self.anthropic.tool_use_loop(messages, tools)
            except Exception as e:
                errors.append(f"Anthropic({self.anthropic.model}): {e}")
                print(f"[warn] Anthropic tool-loop failed: {e}; falling back to OpenRouter")
        if self.openrouter.api_key:
            try:
                self.openrouter._current_model = self.model_chain[0]
                return await self.openrouter.tool_use_loop(messages, tools)
            except Exception as e:
                errors.append(f"OpenRouter({self.model_chain[0]}): {e}")
                print(f"[warn] OpenRouter tool-loop failed: {e}; falling back to NIM")
        if self.nvidia.api_key:
            # Prefer a tool-capable NIM model (llama-3.3-70b handles function calls).
            nim_model = next((m for m in self.model_chain if "meta/" in m or "nvidia/" in m), None)
            if nim_model:
                self.nvidia.model = nim_model
            try:
                return await self.nvidia.tool_use_loop(messages, tools)
            except Exception as e:
                errors.append(f"NIM({self.nvidia.model}): {e}")
        raise RuntimeError("All LLM providers failed for tool-use: " + "; ".join(errors) or "No LLM provider available")