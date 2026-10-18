from app.core.settings import AgentConfig
from app.providers.base import LLMProvider
from app.providers.demo_script import DEMO_SCRIPTS
from app.providers.mock import MockProvider, MockScript


def build_provider(cfg: AgentConfig, script: MockScript | None = None) -> LLMProvider:
    """Build the provider for one agent. Real providers arrive in M2."""
    if cfg.provider == "mock":
        if script is None:
            factory = DEMO_SCRIPTS.get(cfg.id)
            if factory is None:
                raise ValueError(f"no demo script for mock agent {cfg.id!r}")
            script = factory()
        return MockProvider(script)
    raise ValueError(f"unknown provider {cfg.provider!r} for agent {cfg.id!r}")
