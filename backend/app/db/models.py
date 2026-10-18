from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel


def _now() -> datetime:
    return datetime.now(UTC)


class Debate(SQLModel, table=True):
    id: str = Field(primary_key=True)
    question: str
    mode: str
    status: str = "running"  # running | completed | failed | interrupted
    created_at: datetime = Field(default_factory=_now)
    config_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    verdict_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    stats_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))


class Turn(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    debate_id: str = Field(foreign_key="debate.id", index=True)
    round: int
    agent_id: str
    agent_label: str
    persona: str
    provider: str
    model: str
    prompt_hash: str
    raw_text: str
    parsed_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    valid: bool
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    fallback_used: bool = False


class DebateEventRow(SQLModel, table=True):
    """The ordered event log: every SSE event of a debate, kept for replay (late joiners, M4)."""

    __tablename__ = "debate_event"
    __table_args__ = (UniqueConstraint("debate_id", "seq"),)

    id: int | None = Field(default=None, primary_key=True)
    debate_id: str = Field(foreign_key="debate.id", index=True)
    seq: int
    type: str
    data: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))


class CacheEntry(SQLModel, table=True):
    """Cached successful completion, keyed on (provider, model, params, messages, json_mode)."""

    key_hash: str = Field(primary_key=True)
    response_text: str
    tokens_in: int = 0
    tokens_out: int = 0
    provider: str = ""
    model: str = ""
    created_at: datetime = Field(default_factory=_now)
