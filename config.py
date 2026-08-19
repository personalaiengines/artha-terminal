"""
ARTHA Terminal - Configuration Loader
Loads environment variables and provides configuration management.
"""

import os
from pathlib import Path
from dotenv import load_dotenv
from dataclasses import dataclass
from typing import Optional

# Load .env file
load_dotenv()


class ProviderKey:
    """A credential field that is read LIVE on every access:
    the signed-in user's stored key first, the `.env` value second, else None.

    This exists because ~30 call sites already read `config.upstox.analytics_token`
    or `config.ai.groq_api_key` directly. Making the *read* dynamic keeps every
    one of them working unchanged while a key saved through the API takes effect
    on the very next request — the alternative was rewriting each call site to
    ask a resolver, which is a far larger diff for the same behaviour.

    The `.env` value is the instance attribute set by `Config.__init__` (and by
    tests/monkeypatch, which is why it stays writable). It is the fallback that
    keeps ingestion and the scheduler — which run with no user — working.
    """
    __slots__ = ("env", "attr")

    def __init__(self, env: str):
        self.env = env

    def __set_name__(self, owner, name):
        self.attr = "_" + name

    def __get__(self, obj, owner=None):
        if obj is None:
            return None  # dataclass reads this as the field's default
        try:
            from services.auth import user_key
            stored = user_key(self.env)
        except Exception:
            # No auth module, no database yet, no ARTHA_SECRET_KEY: none of
            # those should make a configured .env key unreadable.
            stored = None
        return stored or getattr(obj, self.attr, None)

    def __set__(self, obj, value):
        setattr(obj, self.attr, value)


@dataclass
class TierSpec:
    """One rung of a task-shape routing chain: which client + which model."""
    provider: str  # key into ModelRouter's client dict: sambanova/github/openrouter/nvidia
    model: str


@dataclass
class AIConfig:
    """AI/LLM configuration with fallback hierarchy."""
    provider: str = "openrouter"  # openrouter (free models, primary), nvidia (fallback)
    primary_model: str = "nvidia/nemotron-3-ultra-550b-a55b:free"
    fallback_model_1: str = "nvidia/nemotron-3-super-120b-a12b:free"
    # Both original NIM rungs were dead. Probed live against
    # integrate.api.nvidia.com on 2026-07-30: meta/llama-3.1-405b-instruct ->
    # HTTP 404 (retired), qwen/qwen3-next-80b-a3b-instruct (what .env.example
    # recommended) -> HTTP 410 Gone, meta/llama-3.3-70b-instruct -> no answer
    # inside 70s. All three could never win a race they were configured to run.
    #
    # Replacements chosen by probing the whole catalogue with the app's real
    # tool-calling prompt, fastest-first (all HTTP 200 with a clean tool_call):
    #   mistralai/mistral-nemotron            0.6s
    #   deepseek-ai/deepseek-v4-pro           1.4s
    #   deepseek-ai/deepseek-v4-flash         8.3s
    #   nvidia/llama-3.3-nemotron-super-49b   7.3s
    #   z-ai/glm-5.2                         31.8s   (works, too slow to rank)
    #   minimaxai/minimax-m3                 31.3s   (and returned no tool_call)
    # Empty = disabled. A model id goes in only after `scripts/ai_check.py models`
    # shows it answering.
    fallback_model_2: str = "mistralai/mistral-nemotron"
    fallback_model_3: str = "deepseek-ai/deepseek-v4-pro"

    # Groq — fastest rung by an order of magnitude (0.5s vs 7-25s), 131K context,
    # tool-calling verified. Serves both task shapes, so it leads both chains.
    groq_api_key: Optional[str] = ProviderKey("GROQ_API_KEY")
    groq_model: str = "openai/gpt-oss-120b"

    # Google Gemini free tier, via Google's OpenAI-compatible endpoint. A quota
    # pool independent of SambaNova/OpenRouter, which both 429 regularly.
    # Probed live: gemini-flash-latest 3.3s, gemini-flash-lite-latest 0.5s, both
    # returning proper tool_calls.
    google_api_key: Optional[str] = ProviderKey("GOOGLE_API_KEY")
    google_model: str = "gemini-flash-latest"

    # Direct Anthropic API — OPTIONAL, PAID. Off unless ANTHROPIC_API_KEY is
    # explicitly set; the free tiered chain below is the default path.
    anthropic_api_key: Optional[str] = ProviderKey("ANTHROPIC_API_KEY")
    anthropic_model: str = "claude-sonnet-5"

    # API Keys
    openrouter_api_key: Optional[str] = ProviderKey("OPENROUTER_API_KEY")
    nvidia_api_key: Optional[str] = ProviderKey("NVIDIA_API_KEY")
    sambanova_api_key: Optional[str] = ProviderKey("SAMBANOVA_API_KEY")
    # GitHub PAT with `models: read`
    github_models_token: Optional[str] = ProviderKey("GITHUB_MODELS_TOKEN")

    sambanova_model: str = "Meta-Llama-3.3-70B-Instruct"
    github_models_model: str = "Llama-3.3-70B-Instruct"

    # Approximate free-tier context ceiling used as a routing/compression
    # signal only — providers don't guarantee this exactly.
    SAMBANOVA_CONTEXT_CEILING: int = 8000

    @property
    def has_anthropic(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def has_openrouter(self) -> bool:
        return bool(self.openrouter_api_key)

    @property
    def has_nvidia(self) -> bool:
        return bool(self.nvidia_api_key)

    @property
    def has_sambanova(self) -> bool:
        return bool(self.sambanova_api_key)

    @property
    def has_github_models(self) -> bool:
        return bool(self.github_models_token)

    @property
    def has_groq(self) -> bool:
        return bool(self.groq_api_key)

    @property
    def has_google(self) -> bool:
        return bool(self.google_api_key)

    def get_tier_chain(self, task_shape: str = "deep") -> list["TierSpec"]:
        """Ordered free-tier chain to try for a given task shape.

        Groq leads both shapes: measured live it answers in 0.5s against 7-25s
        for every other rung, carries a 131K context so it suits `deep` as well
        as `quick`, and calls tools correctly. Everything below it is a fallback
        for when its free quota runs out.

        'quick': small/fast tasks (sentiment tags, curation, debate turns) —
                 then SambaNova (fast, small context), then the general chain.
        'deep':  long-context tasks (report synthesis, full history) —
                 then GitHub Models (128K context), then the general chain.
        """
        chain: list[TierSpec] = []
        if self.has_groq:
            chain.append(TierSpec("groq", self.groq_model))
        # Second, on an independent quota pool — the rung most likely to still be
        # answering when Groq's free allowance runs out.
        if self.has_google:
            chain.append(TierSpec("google", self.google_model))
        if task_shape == "quick" and self.has_sambanova:
            chain.append(TierSpec("sambanova", self.sambanova_model))
        if task_shape == "deep" and self.has_github_models:
            chain.append(TierSpec("github", self.github_models_model))
        if self.has_openrouter:
            chain.append(TierSpec("openrouter", self.primary_model))
            chain.append(TierSpec("openrouter", self.fallback_model_1))
        if self.has_nvidia:
            chain.append(TierSpec("nvidia", self.fallback_model_2))
            chain.append(TierSpec("nvidia", self.fallback_model_3))
        # SambaNova is a separate free quota pool from OpenRouter/NIM — always
        # keep it as a last-resort rung (front of chain already covers 'quick').
        if task_shape == "deep" and self.has_sambanova:
            chain.append(TierSpec("sambanova", self.sambanova_model))
        # A rung with no model id is a disabled rung, not a rung that tries "".
        return [t for t in chain if t.model]


@dataclass
class SearchConfig:
    """Search API configuration."""
    provider: str = "serpapi"
    serpapi_key: Optional[str] = ProviderKey("SERPAPI_KEY")
    serper_api_key: Optional[str] = ProviderKey("SERPER_API_KEY")
    bing_api_key: Optional[str] = ProviderKey("BING_API_KEY")
    jina_api_key: Optional[str] = ProviderKey("JINA_API_KEY")
    searxng_url: str = "http://localhost:8080"
    finnhub_api_key: Optional[str] = ProviderKey("FINNHUB_API_KEY")

    @property
    def has_serpapi(self) -> bool:
        return bool(self.serpapi_key)

    @property
    def has_finnhub(self) -> bool:
        return bool(self.finnhub_api_key)

    @property
    def has_serper(self) -> bool:
        return bool(self.serper_api_key)

    @property
    def has_searxng(self) -> bool:
        return bool(self.searxng_url and self.searxng_url != "http://localhost:8080")


@dataclass
class UpstoxConfig:
    """Upstox broker API configuration."""
    analytics_token: Optional[str] = ProviderKey("UPSTOX_ANALYTICS_TOKEN")
    client_id: Optional[str] = ProviderKey("UPSTOX_CLIENT_ID")
    client_secret: Optional[str] = ProviderKey("UPSTOX_CLIENT_SECRET")
    access_token: Optional[str] = ProviderKey("UPSTOX_ACCESS_TOKEN")
    redirect_uri: str = "http://localhost:3000/upstox/callback"

    def authorize_url(self) -> str:
        """Upstox OAuth login URL — user logs in here to mint a daily code."""
        from urllib.parse import urlencode
        params = {
            "response_type": "code",
            "client_id": self.client_id or "",
            "redirect_uri": self.redirect_uri,
        }
        return "https://api.upstox.com/v2/login/authorization/dialog?" + urlencode(params)

    @property
    def is_configured(self) -> bool:
        return bool(self.analytics_token and self.client_id)

    @property
    def can_access_market_data(self) -> bool:
        return bool(self.analytics_token)

    @property
    def can_access_portfolio(self) -> bool:
        return bool(self.client_id and self.client_secret and self.access_token)


@dataclass
class AppConfig:
    """Application-wide settings."""
    port: int = 8501
    log_level: str = "INFO"
    demo_mode: bool = False
    debug: bool = False


class Config:
    """Main configuration manager."""

    def __init__(self):
        self.project_root = Path(__file__).parent
        self.ai = AIConfig(
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
            anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5"),
            openrouter_api_key=os.getenv("OPENROUTER_API_KEY"),
            nvidia_api_key=os.getenv("NVIDIA_API_KEY"),
            # `or AIConfig.<field>` rather than a literal getenv default: the
            # literals here used to be anthropic/claude-sonnet-4.5 and
            # google/gemini-2.5-flash, which silently overrode the free-tier
            # defaults declared on AIConfig and billed anyone who set only an
            # OpenRouter key. One source of truth, and it is the free one.
            primary_model=os.getenv("OPENROUTER_PRIMARY_MODEL") or AIConfig.primary_model,
            fallback_model_1=os.getenv("OPENROUTER_FALLBACK_MODEL") or AIConfig.fallback_model_1,
            fallback_model_2=os.getenv("NVIDIA_FALLBACK_MODEL") or AIConfig.fallback_model_2,
            fallback_model_3=os.getenv("NVIDIA_BACKUP_MODEL") or AIConfig.fallback_model_3,
            sambanova_api_key=os.getenv("SAMBANOVA_API_KEY"),
            sambanova_model=os.getenv("SAMBANOVA_MODEL") or AIConfig.sambanova_model,
            github_models_token=os.getenv("GITHUB_MODELS_TOKEN"),
            github_models_model=os.getenv("GITHUB_MODELS_MODEL") or AIConfig.github_models_model,
            groq_api_key=os.getenv("GROQ_API_KEY"),
            groq_model=os.getenv("GROQ_MODEL") or AIConfig.groq_model,
            google_api_key=os.getenv("GOOGLE_API_KEY"),
            google_model=os.getenv("GOOGLE_MODEL") or AIConfig.google_model,
        )
        self.search = SearchConfig(
            serpapi_key=os.getenv("SERPAPI_KEY"),
            serper_api_key=os.getenv("SERPER_API_KEY"),
            bing_api_key=os.getenv("BING_API_KEY"),
            jina_api_key=os.getenv("JINA_API_KEY"),
            searxng_url=os.getenv("SEARXNG_URL", "http://localhost:8080"),
            finnhub_api_key=os.getenv("FINNHUB_API_KEY"),
        )
        self.upstox = UpstoxConfig(
            analytics_token=os.getenv("UPSTOX_ANALYTICS_TOKEN"),
            client_id=os.getenv("UPSTOX_CLIENT_ID"),
            client_secret=os.getenv("UPSTOX_CLIENT_SECRET"),
            access_token=os.getenv("UPSTOX_ACCESS_TOKEN"),
            redirect_uri=os.getenv("UPSTOX_REDIRECT_URI", "http://localhost:3000/upstox/callback"),
        )
        self.app = AppConfig(
            port=int(os.getenv("STREAMLIT_SERVER_PORT", "8501")),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            demo_mode=os.getenv("DEMO_MODE", "false").lower() == "true",
            debug=os.getenv("DEBUG", "false").lower() == "true",
        )

        # Database paths
        # Support Docker volume mount via ARTHA_DB_PATH env var
        db_path_env = os.getenv("ARTHA_DB_PATH")
        if db_path_env:
            self.db_path = Path(db_path_env)
        else:
            self.db_path = self.project_root / "db" / "artha.db"
        self.cache_path = self.project_root / "db" / "cache"
        self.logs_path = self.project_root / "logs"

        # Persisted Upstox access token (regenerated in-app). Lives next to the DB
        # so it survives restarts and works in Docker via the mounted volume. A
        # saved token takes precedence over the .env value.
        self.upstox_token_file = self.db_path.parent / "upstox_access_token.json"
        try:
            if self.upstox_token_file.exists():
                import json
                saved = json.loads(self.upstox_token_file.read_text(encoding="utf-8"))
                if saved.get("access_token"):
                    self.upstox.access_token = saved["access_token"]
        except Exception:
            pass

    def validate(self) -> list[str]:
        """Validate configuration and return list of warnings/errors."""
        warnings = []

        # Check AI configuration
        if not any([self.ai.has_openrouter, self.ai.has_nvidia, self.ai.has_sambanova,
                    self.ai.has_github_models, self.ai.has_anthropic]):
            warnings.append("⚠️ No AI provider configured. Set OPENROUTER_API_KEY, NVIDIA_API_KEY, "
                             "SAMBANOVA_API_KEY, or GITHUB_MODELS_TOKEN (all free-tier). "
                             "ANTHROPIC_API_KEY is optional and paid.")

        # Check search configuration
        if not self.search.has_serpapi and not self.search.has_serper:
            warnings.append("⚠️ No search provider configured. Set SERPAPI_KEY or SERPER_API_KEY.")

        # Check Upstox configuration
        if not self.upstox.is_configured:
            warnings.append("⚠️ Upstox not configured. Market data and portfolio features won't work.")

        return warnings

    def get_api_base_url(self, provider: str) -> str:
        """Get API base URL for provider."""
        urls = {
            "openrouter": "https://openrouter.ai/api/v1/chat/completions",
            "nvidia": "https://integrate.api.nvidia.com/v1/chat/completions",
        }
        return urls.get(provider, urls["openrouter"])


# Global config instance
config = Config()

__all__ = ["config", "Config", "AIConfig", "SearchConfig", "UpstoxConfig", "AppConfig"]