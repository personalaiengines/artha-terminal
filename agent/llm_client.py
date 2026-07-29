"""
ARTHA Terminal - Agent LLM Client
OpenRouter and Nvidia NIM API support with automatic fallback.
"""

import httpx
import json
import time
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

        payload = {"model": self._current_model, "messages": messages}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        async with httpx.AsyncClient(timeout=25.0) as client:
            response = await client.post(self.base_url, headers=headers, json=payload)

            if response.status_code == 401:
                raise ValueError("OpenRouter API key invalid or exhausted")

            response.raise_for_status()
            return response.json()

    async def tool_use_loop(
        self, messages: list, tools: list[Callable]
    ) -> tuple[str, list]:
        return await _generic_tool_use_loop(self, messages, tools)


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

        payload = {"model": self.model, "messages": messages}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        async with httpx.AsyncClient(timeout=25.0) as client:
            response = await client.post(self.base_url, headers=headers, json=payload)
            response.raise_for_status()
            return response.json()

    async def tool_use_loop(
        self, messages: list, tools: list[Callable]
    ) -> tuple[str, list]:
        return await _generic_tool_use_loop(self, messages, tools)


class SambaNovaClient(LLMClient):
    """SambaNova Cloud free tier — fast, small (~8K) context. Same OpenAI-chat
    shape as OpenRouter/NIM, plain bearer-token REST, no vendor SDK needed."""

    def __init__(self):
        self.base_url = "https://api.sambanova.ai/v1/chat/completions"
        self.api_key = config.ai.sambanova_api_key
        self.model = config.ai.sambanova_model

    async def chat(self, messages: list, tools: list = None) -> dict:
        if not self.api_key:
            raise ValueError("SambaNova API key not configured")

        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {"model": self.model, "messages": messages}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        async with httpx.AsyncClient(timeout=25.0) as client:
            response = await client.post(self.base_url, headers=headers, json=payload)
            if response.status_code == 401:
                raise ValueError("SambaNova API key invalid or exhausted")
            response.raise_for_status()
            return response.json()

    async def tool_use_loop(self, messages: list, tools: list[Callable]) -> tuple[str, list]:
        return await _generic_tool_use_loop(self, messages, tools)


class GitHubModelsClient(LLMClient):
    """GitHub Models free tier — 128K context, auth via a GitHub PAT
    (`models: read` scope) rather than a vendor API key."""

    def __init__(self):
        self.base_url = "https://models.inference.ai.azure.com/chat/completions"
        self.api_key = config.ai.github_models_token
        self.model = config.ai.github_models_model

    async def chat(self, messages: list, tools: list = None) -> dict:
        if not self.api_key:
            raise ValueError("GitHub Models token not configured")

        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {"model": self.model, "messages": messages}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        async with httpx.AsyncClient(timeout=25.0) as client:
            response = await client.post(self.base_url, headers=headers, json=payload)
            if response.status_code == 401:
                raise ValueError("GitHub Models token invalid or exhausted")
            response.raise_for_status()
            return response.json()

    async def tool_use_loop(self, messages: list, tools: list[Callable]) -> tuple[str, list]:
        return await _generic_tool_use_loop(self, messages, tools)


async def _generic_tool_use_loop(client: LLMClient, messages: list, tools: list[Callable]) -> tuple[str, list]:
    """Shared tool-use loop body for the OpenAI-chat-shaped clients (same logic
    OpenRouterClient/NvidiaNIMClient already duplicate) — reused by the two new
    tiers instead of copy-pasting a third/fourth time."""
    tool_registry = {t.__name__: t for t in tools}
    max_iterations = 10
    conversation = list(messages)
    tool_calls_log = []

    for _ in range(max_iterations):
        response = await client.chat(conversation, tools=list(tool_registry.keys()))
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


def _request_parts(client: LLMClient) -> tuple[str, dict, str]:
    """(url, headers, model) for the four OpenAI-chat-shaped clients."""
    model = client._current_model if isinstance(client, OpenRouterClient) else client.model
    headers = {"Authorization": f"Bearer {client.api_key}", "Content-Type": "application/json"}
    if isinstance(client, OpenRouterClient):
        headers |= {"HTTP-Referer": "https://artha.local", "X-Title": "ARTHA Terminal"}
    return client.base_url, headers, model


async def _stream_openai_chat(client: LLMClient, messages: list):
    """Yield text deltas from an OpenAI-shaped /chat/completions SSE stream.

    All four free tiers speak the same `data: {...}` / `data: [DONE]` wire
    format, so one helper covers them. Tools are deliberately not supported
    here — streaming is only for the final narrative turn, after any tool work
    has already finished.
    """
    if not client.api_key:
        raise ValueError(f"{type(client).__name__} not configured")
    url, headers, model = _request_parts(client)
    payload = {"model": model, "messages": messages, "stream": True}
    async with httpx.AsyncClient(timeout=120.0) as http:
        async with http.stream("POST", url, headers=headers, json=payload) as resp:
            if resp.status_code >= 400:
                # Body must be read before the status error is useful, and
                # raise_for_status() on an unread stream gives no detail.
                await resp.aread()
                resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    return
                try:
                    delta = json.loads(data)["choices"][0]["delta"].get("content")
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
                if delta:
                    yield delta


class AllTiersExhausted(RuntimeError):
    """Every free-tier LLM (and, if opted-in, paid Anthropic) failed. Distinct
    from other RuntimeErrors so callers can surface a specific "AI temporarily
    unavailable" message instead of a generic failure."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("All free-tier LLM providers exhausted: " + "; ".join(errors))


class ModelRouter:
    """Tiered free-only router. Anthropic is opt-in only (paid, used solely if
    ANTHROPIC_API_KEY is explicitly set) — never part of the default chain.

    `task_shape` picks which free tier goes first:
      'quick' — sentiment/curation/debate turns: SambaNova first (fast, small context)
      'deep'  — report synthesis/long context: GitHub Models first (128K context)
    Both shapes fall through the same OpenRouter-free → NIM-free rungs after that.
    """

    # Runtime skip-list: a tier that 404/410s (model retired) or 429s (quota
    # hit) gets cooled down automatically so it doesn't eat a guaranteed-fail
    # round trip on every subsequent request — self-heals when the cooldown
    # expires, no config edit needed. Class-level: ModelRouter is constructed
    # fresh per request, but the skip-list must survive across requests.
    _cooldown: dict[str, float] = {}

    def __init__(self):
        self.anthropic = AnthropicClient()
        self.clients: dict[str, LLMClient] = {
            "openrouter": OpenRouterClient(),
            "nvidia": NvidiaNIMClient(),
            "sambanova": SambaNovaClient(),
            "github": GitHubModelsClient(),
        }

    @staticmethod
    def _cooldown_seconds(exc: Exception) -> Optional[int]:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (404, 410):
            return 6 * 3600   # model retired/removed upstream
        if status == 429:
            return 5 * 60     # rate limited — quota resets fast
        return None            # transient (timeout/5xx/connection) — retry next request

    @staticmethod
    def _set_model(client: LLMClient, model: str) -> None:
        if isinstance(client, OpenRouterClient):
            client._current_model = model
        else:
            client.model = model

    @staticmethod
    def _compress_if_needed(tier, messages: list) -> list:
        """Only SambaNova has a small free-tier context ceiling worth
        compressing for — GitHub Models (128K), OpenRouter and NIM don't need
        this, so skip the (lossy) compression pass for them entirely."""
        if tier.provider != "sambanova":
            return messages
        from agent.context_window import compress_for_tier
        return compress_for_tier(messages, config.ai.SAMBANOVA_CONTEXT_CEILING)

    @staticmethod
    def _chain_for(task_shape: str, tools: list = None) -> list:
        """GitHub Models' free-tier gateway rejects this app's full tool
        registry (8 schemas + a long system prompt) — 400 on the very first
        tool-bearing call, 413 on every one after as the conversation grows.
        Verified against the real endpoint: a single small tool schema works
        fine, the full registry doesn't. Every tool-loop iteration was wasting
        a guaranteed-fail round-trip on it before falling through to
        OpenRouter — skip it whenever tools are attached, not worth vendoring
        a payload-splitting workaround for a free tier."""
        chain = config.ai.get_tier_chain(task_shape)
        if tools:
            chain = [t for t in chain if t.provider != "github"]
        now = time.time()
        available = [t for t in chain if ModelRouter._cooldown.get(f"{t.provider}:{t.model}", 0) <= now]
        return available or chain  # all cooled down — try anyway rather than give up with zero attempts

    async def chat(self, messages: list, tools: list = None, task_shape: str = "deep") -> dict:
        if self.anthropic.api_key:
            try:
                return await self.anthropic.chat(messages, tools)
            except Exception as e:
                print(f"[warn] Anthropic failed ({self.anthropic.model}): {e}; falling back")

        errors = []
        for tier in self._chain_for(task_shape, tools):
            client = self.clients[tier.provider]
            self._set_model(client, tier.model)
            tier_messages = self._compress_if_needed(tier, messages)
            key = f"{tier.provider}:{tier.model}"
            try:
                result = await client.chat(tier_messages, tools)
                self._cooldown.pop(key, None)
                return result
            except Exception as e:
                errors.append(f"{tier.provider}({tier.model}): {e}")
                print(f"[warn] Provider failed ({tier.provider}/{tier.model}): {e}")
                secs = self._cooldown_seconds(e)
                if secs:
                    self._cooldown[key] = time.time() + secs
                    print(f"[warn] Cooling down {key} for {secs}s")
                continue

        raise AllTiersExhausted(errors)

    async def stream(self, messages: list, task_shape: str = "deep"):
        """Yield text deltas, walking the same tier chain (and cooldowns) as chat().

        Anthropic is skipped even when opted in — it's a different wire format
        and this path is only used by the conversational UI, which runs on the
        free chain by design.
        """
        errors = []
        for tier in self._chain_for(task_shape):
            client = self.clients[tier.provider]
            self._set_model(client, tier.model)
            key = f"{tier.provider}:{tier.model}"
            sent = False
            try:
                async for delta in _stream_openai_chat(client, self._compress_if_needed(tier, messages)):
                    sent = True
                    yield delta
            except Exception as e:
                if sent:
                    # Text already reached the user. Failing over now would
                    # restart the answer mid-sentence in the UI — stop instead.
                    print(f"[warn] Stream broke mid-answer ({key}): {e}")
                    return
                errors.append(f"{tier.provider}({tier.model}): {e}")
                secs = self._cooldown_seconds(e)
                if secs:
                    self._cooldown[key] = time.time() + secs
                continue
            if sent:
                self._cooldown.pop(key, None)
                return
            errors.append(f"{tier.provider}({tier.model}): empty stream")
        raise AllTiersExhausted(errors)

    async def tool_use_loop(
        self, messages: list, tools: list[Callable], task_shape: str = "deep"
    ) -> tuple[str, list]:
        if self.anthropic.api_key:
            try:
                return await self.anthropic.tool_use_loop(messages, tools)
            except Exception as e:
                print(f"[warn] Anthropic tool-loop failed: {e}; falling back")

        errors = []
        for tier in self._chain_for(task_shape, tools):
            client = self.clients[tier.provider]
            self._set_model(client, tier.model)
            tier_messages = self._compress_if_needed(tier, messages)
            key = f"{tier.provider}:{tier.model}"
            try:
                result = await client.tool_use_loop(tier_messages, tools)
                self._cooldown.pop(key, None)
                return result
            except Exception as e:
                errors.append(f"{tier.provider}({tier.model}): {e}")
                print(f"[warn] Provider tool-loop failed ({tier.provider}/{tier.model}): {e}")
                secs = self._cooldown_seconds(e)
                if secs:
                    self._cooldown[key] = time.time() + secs
                    print(f"[warn] Cooling down {key} for {secs}s")
                continue

        raise AllTiersExhausted(errors)