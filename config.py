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


@dataclass
class AIConfig:
    """AI/LLM configuration with fallback hierarchy."""
    provider: str = "openrouter"  # openrouter (free models, primary), nvidia (fallback)
    primary_model: str = "nvidia/nemotron-3-ultra-550b-a55b:free"
    fallback_model_1: str = "nvidia/nemotron-3-super-120b-a12b:free"
    fallback_model_2: str = "qwen/qwen3-next-80b-a3b-instruct"
    fallback_model_3: str = "meta/llama-3.3-70b-instruct"

    # Direct Anthropic API — OPTIONAL, PAID. Off unless ANTHROPIC_API_KEY is
    # explicitly set; the free OpenRouter/NIM chain below is the default path.
    anthropic_api_key: Optional[str] = None
    anthropic_model: str = "claude-sonnet-5"

    # API Keys
    openrouter_api_key: Optional[str] = None
    nvidia_api_key: Optional[str] = None

    @property
    def has_anthropic(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def has_openrouter(self) -> bool:
        return bool(self.openrouter_api_key)

    @property
    def has_nvidia(self) -> bool:
        return bool(self.nvidia_api_key)

    def get_model_chain(self) -> list[str]:
        """Return ordered list of models to try."""
        chain = []
        if self.has_openrouter:
            chain.extend([self.primary_model, self.fallback_model_1])
        if self.has_nvidia:
            chain.extend([self.fallback_model_2, self.fallback_model_3])
        return chain


@dataclass
class SearchConfig:
    """Search API configuration."""
    provider: str = "serpapi"
    serpapi_key: Optional[str] = None
    serper_api_key: Optional[str] = None
    bing_api_key: Optional[str] = None
    jina_api_key: Optional[str] = None
    searxng_url: str = "http://localhost:8080"

    @property
    def has_serpapi(self) -> bool:
        return bool(self.serpapi_key)

    @property
    def has_serper(self) -> bool:
        return bool(self.serper_api_key)

    @property
    def has_searxng(self) -> bool:
        return bool(self.searxng_url and self.searxng_url != "http://localhost:8080")


@dataclass
class UpstoxConfig:
    """Upstox broker API configuration."""
    analytics_token: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    access_token: Optional[str] = None
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
            primary_model=os.getenv("OPENROUTER_PRIMARY_MODEL", "anthropic/claude-sonnet-4.5"),
            fallback_model_1=os.getenv("OPENROUTER_FALLBACK_MODEL", "google/gemini-2.5-flash"),
            fallback_model_2=os.getenv("NVIDIA_FALLBACK_MODEL", "qwen/qwen3-next-80b-a3b-instruct"),
            fallback_model_3=os.getenv("NVIDIA_BACKUP_MODEL", "meta/llama-3.3-70b-instruct"),
        )
        self.search = SearchConfig(
            serpapi_key=os.getenv("SERPAPI_KEY"),
            serper_api_key=os.getenv("SERPER_API_KEY"),
            bing_api_key=os.getenv("BING_API_KEY"),
            jina_api_key=os.getenv("JINA_API_KEY"),
            searxng_url=os.getenv("SEARXNG_URL", "http://localhost:8080"),
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
        if not self.ai.has_openrouter and not self.ai.has_nvidia and not self.ai.has_anthropic:
            warnings.append("⚠️ No AI provider configured. Set OPENROUTER_API_KEY or NVIDIA_API_KEY (both free-tier). ANTHROPIC_API_KEY is optional and paid.")

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