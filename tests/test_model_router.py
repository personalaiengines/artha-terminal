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

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import config
from agent.llm_client import ModelRouter, AllTiersExhausted


def _configure_all_tiers(fast_tiers: bool = False):
    config.ai.sambanova_api_key = "sb-key"
    config.ai.github_models_token = "gh-pat"
    config.ai.openrouter_api_key = "or-key"
    config.ai.nvidia_api_key = "nv-key"
    config.ai.anthropic_api_key = None  # keep the opt-in paid path off
    
    # Groq and Google lead both chains in production. Both are OFF by default here
    # so the tests below keep asserting what they were written to assert — the RELATIVE
    # preferences further down the chain (quick -> sambanova, deep -> github,
    # github skipped when tools are attached). Groq's own position is covered by
    # the two dedicated tests at the end of this file.
    config.ai.groq_api_key = "groq-key" if fast_tiers else None
    config.ai.google_api_key = "goog-key" if fast_tiers else None
    # Class-level state — reset so tests don't leak into each other. The 429
    # streak matters as much as the cooldown: three leaked 429s would flip the
    # next test's cooldown from 5 minutes to an hour.
    ModelRouter._cooldown.clear()
    ModelRouter._429_streak.clear()


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

    # Every configured rung must be tried and reported, whatever the chain length
    # currently is. This used to hard-code 5; disabling a dead NIM rung then broke
    # it for the right reason but the wrong assertion. What matters is that the
    # error names every rung actually attempted, not that there are N of them.
    expected = config.ai.get_tier_chain("quick")
    assert len(exc_info.value.errors) == len(expected)
    for tier in expected:
        assert any(tier.model in e for e in exc_info.value.errors), f"{tier.model} not reported"


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


def _http_status_error(status: int) -> httpx.HTTPStatusError:
    """The real exception raise_for_status() produces — carries .response."""
    request = httpx.Request("POST", "https://example.test/chat/completions")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError(f"HTTP {status}", request=request, response=response)


def test_invalid_key_cools_down_for_six_hours():
    """An expired/revoked key doesn't heal on its own — retrying it every call
    burns a full round trip forever. Three clients used to raise a bare
    ValueError on 401, which carries no .response, so _cooldown_seconds could
    never classify it."""
    assert ModelRouter._cooldown_seconds(_http_status_error(401)) == 6 * 3600
    assert ModelRouter._cooldown_seconds(_http_status_error(403)) == 6 * 3600


def test_repeated_429_escalates_from_minutes_to_an_hour():
    """A daily-capped rung (SambaNova, OpenRouter free) 429s identically to a
    per-minute-capped one (Groq), and neither sends Retry-After. Five minutes is
    right for the second and wrong for the first, so a streak escalates."""
    ModelRouter._429_streak.clear()
    key = "sambanova:test-model"
    err = _http_status_error(429)
    assert ModelRouter._cooldown_seconds(err, key) == 5 * 60
    assert ModelRouter._cooldown_seconds(err, key) == 5 * 60
    assert ModelRouter._cooldown_seconds(err, key) == 3600, "third strike = capped, not busy"


def test_success_clears_the_429_streak():
    ModelRouter._429_streak.clear()
    key = "groq:test-model"
    err = _http_status_error(429)
    ModelRouter._cooldown_seconds(err, key)
    ModelRouter._cooldown_seconds(err, key)
    ModelRouter._429_streak.pop(key, None)  # what a successful call does
    assert ModelRouter._cooldown_seconds(err, key) == 5 * 60


def test_server_error_is_not_cooled_down():
    """5xx is transient — the next request should still try that tier."""
    assert ModelRouter._cooldown_seconds(_http_status_error(500)) is None


@pytest.mark.asyncio
async def test_groq_leads_both_chains_when_configured():
    """Groq is the first rung for quick AND deep once a key is present.

    It was measured at 0.5s against 7-25s for every other rung, carries a 131K
    context so it suits deep as well as quick, and calls tools correctly. If a
    future edit demotes it, this fails.
    """
    for shape in ("quick", "deep"):
        _configure_all_tiers(fast_tiers=True)
        called = []

        async def fake_post(self, url, headers=None, json=None):
            called.append(url)
            return _ok_response("groq")

        with patch("httpx.AsyncClient.post", new=fake_post):
            await ModelRouter().chat([{"role": "user", "content": "hi"}], task_shape=shape)

        assert "api.groq.com" in called[0], f"{shape}: expected groq first, got {called[0]}"
        assert len(called) == 1, f"{shape}: should short-circuit on the first success"


def test_groq_absent_from_chain_without_a_key():
    """No key must mean no rung — not a rung that tries an empty credential."""
    _configure_all_tiers(fast_tiers=False)
    for shape in ("quick", "deep"):
        assert not any(t.provider == "groq" for t in config.ai.get_tier_chain(shape))


@pytest.mark.asyncio
async def test_google_is_the_second_rung_on_its_own_quota_pool():
    """Groq leads; Google follows on an independent free quota.

    That ordering is the point: SambaNova and OpenRouter both 429 regularly, so
    the second rung has to be a provider whose limits are unrelated to the first.
    """
    _configure_all_tiers(fast_tiers=True)
    called = []

    async def fake_post(self, url, headers=None, json=None):
        called.append(url)
        if "groq" in url:
            raise ConnectionError("groq exhausted")
        return _ok_response(json["model"])

    with patch("httpx.AsyncClient.post", new=fake_post):
        await ModelRouter().chat([{"role": "user", "content": "hi"}], task_shape="quick")

    assert "api.groq.com" in called[0]
    assert "generativelanguage.googleapis.com" in called[1], f"expected google second, got {called[1]}"


def test_google_absent_from_chain_without_a_key():
    _configure_all_tiers(fast_tiers=False)
    for shape in ("quick", "deep"):
        assert not any(t.provider == "google" for t in config.ai.get_tier_chain(shape))
