from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

MAX_QUESTION_CHARS = 4000

Severity = Literal["low", "medium", "high"]
Mode = Literal["answer", "review"]


# --- Agent outputs (PRD section 6) ---


class Critique(BaseModel):
    target: str  # "Response N" as seen by the critic; resolved server-side to a real agent id
    issue: str
    severity: Severity


class DebaterOutput(BaseModel):
    reasoning: str
    critiques: list[Critique] = Field(default_factory=list)
    changed_mind: bool = False
    changed_mind_because: str | None = None
    final_answer: str
    confidence: int = Field(ge=0, le=100)


class MistakeCaught(BaseModel):
    description: str
    caught_by: str  # "Debater 2"
    round: int


class JudgeOutput(BaseModel):
    final_answer: str
    confidence: int = Field(ge=0, le=100)
    summary: str
    mistakes_caught: list[MistakeCaught] = Field(default_factory=list)
    dissent: str | None = None
    consensus_reached: bool


# --- API ---


class CreateDebateRequest(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    mode: Mode = "answer"
    rounds: int | None = Field(default=None, ge=1, le=3)

    @field_validator("question")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("question must not be blank")
        return v


class CreateDebateResponse(BaseModel):
    id: str


# --- SSE event payloads (PRD FR2) ---


class AgentInfo(BaseModel):
    label: str
    persona: str


class DebateStarted(BaseModel):
    id: str
    agents: list[AgentInfo]


class AgentThinking(BaseModel):
    round: int
    agent: str


class AgentResponse(BaseModel):
    round: int
    agent: str
    payload: dict[str, Any]  # DebaterOutput plus cluster_id, valid, fallback_used


class CritiqueEdge(BaseModel):
    round: int
    from_agent: str
    to_agent: str
    severity: Severity
    issue: str


class Cluster(BaseModel):
    cluster_id: int
    normalized_answer: str
    agents: list[str]


class RoundComplete(BaseModel):
    round: int
    consensus_score: float
    agreed: bool
    clusters: list[Cluster]


class JudgeVerdict(BaseModel):
    payload: JudgeOutput


class ErrorEvent(BaseModel):
    agent: str | None = None
    message: str
    recoverable: bool


class DoneStats(BaseModel):
    total_tokens: int
    latency_ms: int
    calls: int  # completions requested
    api_calls: int = 0  # HTTP requests actually sent (retries count, cache hits do not)
    cache_hits: int = 0
    fallbacks: int = 0  # completions answered by a fallback provider


class Done(BaseModel):
    stats: DoneStats


EventType = Literal[
    "debate_started",
    "agent_thinking",
    "agent_response",
    "critique_edge",
    "round_complete",
    "judge_verdict",
    "error",
    "done",
]


class DebateEvent(BaseModel):
    """One ordered, persisted event; `seq` is its per-debate position (replay-then-follow)."""

    seq: int
    type: EventType
    data: dict[str, Any]
