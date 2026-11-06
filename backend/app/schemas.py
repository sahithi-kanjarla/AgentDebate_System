from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator

MAX_QUESTION_CHARS = 4000

Severity = Literal["low", "medium", "high"]
Mode = Literal["answer", "review"]

# Validation context for a round-0 answer: there are no peer responses yet, so the prompt asks for
# an empty "critiques" list and anything a model puts there is discarded instead of failing the
# turn. Pass it to parse_with_repair / model_validate only for round 0; later rounds stay strict.
FIRST_ROUND = {"first_round": True}


# --- Agent outputs (original spec section 6) ---


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

    @field_validator("critiques", mode="before")
    @classmethod
    def _drop_first_round_critiques(cls, v: Any, info: ValidationInfo) -> Any:
        """In round 0 there is nothing to critique, so whatever a model wrote here is dropped.

        Only with the FIRST_ROUND validation context. Without it (every critique round in a real
        debate) the value is validated as usual, so a malformed critique still fails the turn.
        """
        return [] if (info.context or {}).get("first_round") else v

    @field_validator("reasoning", mode="before")
    @classmethod
    def _join_reasoning_steps(cls, v: Any) -> Any:
        """Some models write the reasoning as a list of steps, or a dict of them, not one string.

        A list, or a dict's values in order, is joined with newlines: strings as they are, dicts by
        their "description" (else the dict as text), anything else as str(). A string and any other
        type pass through, so the normal type check still applies. final_answer has no leniency.
        """
        if isinstance(v, dict):
            items: Any = list(v.values())
        elif isinstance(v, list):
            items = v
        else:
            return v
        parts = []
        for item in items:
            if isinstance(item, dict):
                desc = item.get("description")
                parts.append(desc if isinstance(desc, str) and desc else str(item))
            else:
                parts.append(item if isinstance(item, str) else str(item))
        return "\n".join(parts)


class MistakeCaught(BaseModel):
    """Built by the server from recorded critiques and answers (see debate/mistakes.py)."""

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


# --- SSE event payloads (original spec FR2) ---


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


class ReceivedCritique(BaseModel):
    """A critique raised against the answer an agent held in the previous round.

    Not a claim that it caused a change: agents do not see critiques addressed to them.
    """

    from_agent: str
    issue: str
    severity: Severity
    round: int


class RoundComplete(BaseModel):
    round: int
    consensus_score: float
    agreed: bool
    clusters: list[Cluster]
    # agent label -> critiques raised this round against the answer that agent revised
    received_critiques: dict[str, list[ReceivedCritique]] = Field(default_factory=dict)


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
