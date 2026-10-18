from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = f"sqlite:///{BACKEND_DIR / 'tribunal.db'}"
    agents_config: Path = BACKEND_DIR / "config" / "agents.yaml"
    default_rounds: int = 3
    min_critique_rounds: int = 1
    shuffle_seed: int = 42


class AgentConfig(BaseModel):
    id: str
    persona: str
    provider: str
    model: str
    persona_prompt: str = ""


class AgentsFile(BaseModel):
    debaters: list[AgentConfig]
    judge: AgentConfig


@lru_cache
def get_settings() -> Settings:
    return Settings()


def load_agents(path: Path | None = None) -> AgentsFile:
    path = path or get_settings().agents_config
    return AgentsFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
