"""
ARTHA Terminal - ModelRouter tiered free-routing tests

Verifies: task_shape picks the right first tier, a mid-chain success
short-circuits remaining tiers, and total exhaustion raises AllTiersExhausted
(not a bare RuntimeError) so callers can distinguish it from other failures.
"""

import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import config
from agent.llm_client import ModelRouter, AllTiersExhausted


def _configure_all_tiers():
    config.ai.sambanova_api_key = "sb-key"
    config.ai.github_models_token = "gh-pat"
    config.ai.openrouter_api_key = "or-key"
    config.ai.nvidia_api_key = "nv-key"
    config.ai.anthropic_api_key = None  # keep the opt-in paid path off
    ModelRouter._cooldown.clear()  # class-level state — reset so tests don't leak into each other


def _ok_response(model_id: str):
    resp = AsyncMock()
    resp.status_code = 200
    resp.raise_for_status = lambda: None
    resp.json = lambda: {
        "choices": [{"message": {"role": "assistant", "content": f"ok from {model_id}"}}],
        "model": model_id,
    }
    return resp


@pytest.mark.asyncio
async def test_quick_shape_tries_sambanova_first():
    _configure_all_tiers()
    router = ModelRouter()

    called_urls = []

    async def fake_post(self, url, headers=None, json=None):
        called_urls.append(url)
        return _ok_response(json["model"])

    with patch("httpx.AsyncClient.post", new=fake_post):
        result = await router.chat([{"role": "user", "content": "hi"}], task_shape="quick")

    assert "sambanova" in called_urls[0]
    assert result["model"] == config.ai.sambanova_model


@pytest.mark.asyncio
async def test_deep_shape_tries_github_models_first():
    _configure_all_tiers()
    router = ModelRouter()

    called_urls = []

    async def fake_post(self, url, headers=None, json=None):
        called_urls.append(url)
        return _ok_response(json["model"])

    with patch("httpx.AsyncClient.post", new=fake_post):
        result = await router.chat([{"role": "user", "content": "hi"}], task_shape="deep")

    assert "models.inference.ai.azure.com" in called_urls[0]
    assert result["model"] == config.ai.github_models_model


@pytest.mark.asyncio
async def test_mid_chain_success_short_circuits_remaining_tiers():
    _configure_all_tiers()
    router = ModelRouter()

    called_urls = []

    async def fake_post(self, url, headers=None, json=None):
        called_urls.append(url)
        if "sambanova" in url:
            raise ConnectionError("sambanova down")
        return _ok_response(json["model"])

    with patch("httpx.AsyncClient.post", new=fake_post):
        result = await router.chat([{"role": "user", "content": "hi"}], task_shape="quick")

    # sambanova failed, next rung (openrouter primary model) succeeded — nvidia
    # rungs after it should never be called.
    assert len(called_urls) == 2
    assert "openrouter" in called_urls[1]
    assert bool(result)


@pytest.mark.asyncio
async def test_deep_shape_skips_github_when_tools_present():
    """GitHub Models' free-tier gateway 400s/413s on this app's full 8-tool
    registry — verified against the real endpoint. Tool-bearing 'deep' calls
    (the orchestration.py tool loop) must skip straight to OpenRouter instead
    of wasting a guaranteed-fail round-trip on GitHub every iteration."""
    _configure_all_tiers()
    router = ModelRouter()

    called_urls = []

    async def fake_post(self, url, headers=None, json=None):
        called_urls.append(url)
        return _ok_response(json["model"])

    tools = [{"type": "function", "function": {"name": "get_price", "parameters": {}}}]
    with patch("httpx.AsyncClient.post", new=fake_post):
        await router.chat([{"role": "user", "content": "hi"}], tools=tools, task_shape="deep")

    assert "models.inference.ai.azure.com" not in called_urls[0]
    assert "openrouter" in called_urls[0]


@pytest.mark.asyncio
async def test_deep_shape_still_tries_github_first_without_tools():
    """Plain (non-tool) 'deep' calls — e.g. the free-form /api/ai chat path —
    aren't affected by the tool-schema payload-size issue, so GitHub Models'
    128K context stays the first rung for them."""
    _configure_all_tiers()
    router = ModelRouter()

    called_urls = []

    async def fake_post(self, url, headers=None, json=None):
        called_urls.append(url)
        return _ok_response(json["model"])

    with patch("httpx.AsyncClient.post", new=fake_post):
        await router.chat([{"role": "user", "content": "hi"}], task_shape="deep")

    assert "models.inference.ai.azure.com" in called_urls[0]


@pytest.mark.asyncio
async def test_all_tiers_exhausted_raises_distinct_error():
    _configure_all_tiers()
    router = ModelRouter()

    async def fake_post(self, url, headers=None, json=None):
        raise ConnectionError("provider down")

    with patch("httpx.AsyncClient.post", new=fake_post):
        with pytest.raises(AllTiersExhausted) as exc_info:
            await router.chat([{"role": "user", "content": "hi"}], task_shape="quick")

    assert len(exc_info.value.errors) == 5  # sambanova + 2 openrouter + 2 nvidia rungs


class _FakeHTTPError(Exception):
    def __init__(self, status_code: int):
        self.response = type("Resp", (), {"status_code": status_code})()


@pytest.mark.asyncio
async def test_dead_model_auto_cools_down_without_config_change():
    """A 410 (model retired upstream) must not require a config.py edit to
    stop being retried — the router blacklists that tier in-process and a
    later request routes around it automatically."""
    _configure_all_tiers()

    called_urls = []

    async def fake_post(self, url, headers=None, json=None):
        called_urls.append(url)
        if "sambanova" in url:
            raise _FakeHTTPError(410)
        return _ok_response(json["model"])

    with patch("httpx.AsyncClient.post", new=fake_post):
        await ModelRouter().chat([{"role": "user", "content": "hi"}], task_shape="quick")
    assert "sambanova" in called_urls[0]  # first call still had to try it once

    called_urls.clear()
    with patch("httpx.AsyncClient.post", new=fake_post):
        await ModelRouter().chat([{"role": "user", "content": "hi"}], task_shape="quick")
    assert "sambanova" not in called_urls[0]  # cooled down — skipped without any code change


@pytest.mark.asyncio
async def test_rate_limited_tier_cools_down_shorter_than_dead_model():
    _configure_all_tiers()
    ModelRouter._cooldown["openrouter:" + config.ai.primary_model] = 0  # ensure clean
    now = time.time()

    async def fake_post(self, url, headers=None, json=None):
        raise _FakeHTTPError(429)

    with patch("httpx.AsyncClient.post", new=fake_post):
        with pytest.raises(AllTiersExhausted):
            await ModelRouter().chat([{"role": "user", "content": "hi"}], task_shape="quick")

    key = "openrouter:" + config.ai.primary_model
    remaining = ModelRouter._cooldown[key] - now
    assert 0 < remaining <= 5 * 60 + 5
