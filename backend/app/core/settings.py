from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent

# Names of the Settings fields that hold provider API keys (env vars are the upper-case names).
KEY_SETTINGS = ("gemini_api_key", "groq_api_key", "openrouter_api_key", "mistral_api_key")


class Settings(BaseSettings):
    # Later files win. Keys are loaded here at runtime and never read by anyone else.
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", BACKEND_DIR / ".env"), extra="ignore"
    )

    database_url: str = f"sqlite:///{BACKEND_DIR / 'tribunal.db'}"
    agents_config: Path = BACKEND_DIR / "config" / "agents.yaml"
    default_rounds: int = 3
    min_critique_rounds: int = 1
    shuffle_seed: int = 42
    cache_enabled: bool = True
    log_level: str = "INFO"
    # The built frontend (Vite `dist`). When set and index.html is there, the API serves it, so one
    # process and one port serve everything in the container (the Dockerfile sets FRONTEND_DIST).
    # Unset in local development, which uses the Vite dev server.
    frontend_dist: Path | None = None

    # Public-demo protection (FR10). Off by default so local dev and tests are unaffected; the
    # deployment (Dockerfile / Space secrets) turns it on. Free-tier quotas are shared by every
    # visitor, so besides the per-IP limits there is a global daily cap on real debates.
    rate_limit_enabled: bool = False
    rate_limit_per_hour: int = Field(default=5, ge=1)
    rate_limit_per_day: int = Field(default=20, ge=1)
    # Real debates per UTC day across all visitors; 0 = no cap. Default 15: the tightest free
    # quota (OpenRouter, about 50 requests/day) is hit 2-4 times per debate.
    global_daily_cap: int = Field(default=15, ge=0)
    # Debates running at once (all visitors); 0 = no cap. Independent of rate_limit_enabled.
    max_concurrent_debates: int = Field(default=0, ge=0)
    # Number of trusted reverse proxies in front of the app. 0 = use the socket peer and ignore
    # X-Forwarded-For (cannot be spoofed). N > 0 = take the Nth entry from the right.
    trusted_proxy: int = Field(default=0, ge=0)
    # /api/agents lists provider and model per persona, which un-anonymizes every debate. Only
    # for local dev.
    expose_agent_models: bool = False

    gemini_api_key: SecretStr | None = None
    groq_api_key: SecretStr | None = None
    openrouter_api_key: SecretStr | None = None
    mistral_api_key: SecretStr | None = None

    @field_validator(*KEY_SETTINGS, mode="before")
    @classmethod
    def _blank_key_is_none(cls, v: object) -> object:
        return None if isinstance(v, str) and not v.strip() else v

    def api_key(self, setting_name: str | None) -> str | None:
        """The key behind a Settings field name, or None if unset. Only providers call this."""
        if not setting_name:
            return None
        secret: SecretStr | None = getattr(self, setting_name, None)
        return secret.get_secret_value() if secret else None

    def secret_values(self) -> list[str]:
        """Every configured key value, for the log scrubber."""
        return [v for name in KEY_SETTINGS if (v := self.api_key(name))]


class ModelOptions(BaseModel):
    """Extra request-body fields for one model, e.g. {"reasoning_effort": "low"} on Groq."""

    extra_body: dict[str, Any] = Field(default_factory=dict)


class ProviderConfig(BaseModel):
    base_url: str
    api_key_setting: str | None = None  # Settings field holding the key; None = no key (Ollama)
    max_concurrency: int = Field(default=2, ge=1)
    json_mode: Literal["json_object", "none"] = "json_object"
    timeout_s: float = 60.0
    max_attempts: int = Field(default=3, ge=1)
    # Requests per minute. When set, calls (retries included) are spaced 60/rpm seconds apart
    # instead of bursting into a 429. None = no spacing.
    rpm: float | None = Field(default=None, gt=0)
    # Name of the output-token limit field. Groq deprecated max_tokens for max_completion_tokens.
    token_param: Literal["max_tokens", "max_completion_tokens"] = "max_tokens"
    model_options: dict[str, ModelOptions] = Field(default_factory=dict)  # keyed by model id


class FallbackRef(BaseModel):
    provider: str
    model: str


class AgentConfig(BaseModel):
    id: str
    persona: str
    provider: str
    model: str
    persona_prompt: str = ""
    temperature: float = 0.6
    max_tokens: int | None = None
    fallbacks: list[FallbackRef] = Field(default_factory=list)


class AgentsFile(BaseModel):
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    debaters: list[AgentConfig]
    judge: AgentConfig

    def all_agents(self) -> list[AgentConfig]:
        return [*self.debaters, self.judge]

    def validate_references(self) -> None:
        """Every non-mock provider an agent (or its fallbacks) names must be configured."""
        for agent in self.all_agents():
            for name in [agent.provider, *(f.provider for f in agent.fallbacks)]:
                if name != "mock" and name not in self.providers:
                    raise ValueError(f"agent {agent.id!r} uses unknown provider {name!r}")


@lru_cache
def get_settings() -> Settings:
    return Settings()


def load_agents(path: Path | None = None) -> AgentsFile:
    path = path or get_settings().agents_config
    agents = AgentsFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    agents.validate_references()
    return agents
