"""Run questions through the orchestrator and store derived results.

One question = run D (rounds=3, the app's normal early stop) plus, only when D ran past round 1,
run C (rounds=1, whose rounds 0-1 replay from the response cache so just the judge call is new).
"""

import asyncio
import hashlib
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from app.core.settings import AgentConfig, AgentsFile
from app.debate.orchestrator import Orchestrator, TurnRecord
from app.debate.prompts import PROMPTS_DIR
from app.providers.base import LLMProvider
from eval.budget import Budget, CountingProvider, estimate_per_question
from eval.conditions import (
    JUDGE_LABEL,
    Cost,
    QuestionFacts,
    RunData,
    TurnInfo,
    derive,
    prefix_consistent,
)
from eval.datasets import Dataset, Question
from eval.store import ResultStore

log = logging.getLogger(__name__)

ErrorKind = Literal["model", "quota", "budget", "config", "transient"]

# Errors the model itself caused: unparseable output after the repair attempt. These are real
# results (counted wrong), not infrastructure problems.
# An empty reply that stopped on the output limit (finish_reason=length) is the model running
# out of room, not an outage: hard problems must not be skipped as if they were errors.
_MODEL_MARKERS = (
    "invalid output after repair",
    "judge output invalid after repair",
    "finish_reason=length",
)
_CONFIG_MARKERS = ("unauthorized", "model_not_found", "payment_required", "no_provider")
MAX_ATTEMPTS = 3  # per question per session, for transient errors


def classify_error(message: str) -> ErrorKind:
    text = message.lower()
    if any(m in text for m in _MODEL_MARKERS):
        return "model"
    if "budget_exhausted" in text:
        return "budget"
    if "rate_limited" in text:
        return "quota"
    if any(m in text for m in _CONFIG_MARKERS):
        return "config"
    return "transient"


class QuestionAborted(Exception):
    """The question could not be completed for a non-model reason; nothing is stored for it."""

    def __init__(self, kind: ErrorKind, message: str, provider: str = "") -> None:
        super().__init__(message)
        self.kind = kind
        self.provider = provider


@dataclass
class EvalSettings:
    seed: int = 42
    rounds: int = 3
    min_critique_rounds: int = 1  # the app default; rounds => early stop disabled
    early_stop: bool = True

    @property
    def d_min_critique(self) -> int:
        return self.min_critique_rounds if self.early_stop else self.rounds


def agents_fingerprint(agents: AgentsFile) -> str:
    """Models, generation settings and every prompt file: if it changes, runs are not comparable."""
    h = hashlib.sha256(agents.model_dump_json().encode())
    for path in sorted(PROMPTS_DIR.glob("*.md")):
        h.update(path.name.encode())
        h.update(path.read_bytes())
    return h.hexdigest()[:16]


def _provider_of(agents: AgentsFile, label: str, labels: dict[str, str]) -> str:
    if label == JUDGE_LABEL:
        return agents.judge.provider
    for agent_id, lab in labels.items():
        if lab == label:
            return next(a.provider for a in agents.debaters if a.id == agent_id)
    return ""


def looks_truncated(t: TurnRecord) -> bool:
    """An invalid turn whose output was probably cut off by the token limit.

    Either the provider said so (an empty reply with finish_reason=length), or the last reply
    opened more braces than it closed (JSON cut mid-way). A heuristic: a provider that does
    not report why it stopped cannot be told apart from malformed JSON that happens to be
    unbalanced.
    """
    if t.valid:
        return False
    if "finish_reason=length" in (t.error or ""):
        return True
    text = t.raw_text
    return "{" in text and text.count("{") > text.count("}")


def _turn_info(t: TurnRecord) -> TurnInfo:
    parsed = t.parsed_json or {}
    answer = parsed.get("final_answer") if t.valid else None
    confidence = parsed.get("confidence") if t.valid else None
    return TurnInfo(
        round=t.round,
        label=t.label,
        persona=t.persona,
        provider=t.provider,
        model=t.model,
        fallback_used=t.fallback_used,
        valid=t.valid,
        answer=answer if isinstance(answer, str) else None,
        confidence=confidence if isinstance(confidence, int) else None,
        tokens_in=t.tokens_in,
        tokens_out=t.tokens_out,
        latency_ms=t.latency_ms,
        truncated=looks_truncated(t),
    )


async def drive(orch: Orchestrator, agents: AgentsFile) -> RunData:
    """Run one debate to the end, snapshotting cost at each round. Raises QuestionAborted on any
    error that is not the model's own bad output, as soon as it is seen."""
    started = time.monotonic()

    def cost() -> Cost:
        s = orch.stats
        return Cost(
            s.calls, s.api_calls, s.tokens, int((time.monotonic() - started) * 1000), s.cache_hits
        )

    snapshots: dict[int, Cost] = {}
    total: Cost | None = None
    gen = orch.run()
    try:
        async for type_, data in gen:
            if type_ == "round_complete":
                snapshots[data["round"]] = cost()
            elif type_ == "error":
                kind = classify_error(str(data.get("message", "")))
                if kind != "model":
                    provider = _provider_of(agents, str(data.get("agent", "")), orch.labels)
                    raise QuestionAborted(kind, str(data.get("message")), provider)
            elif type_ == "done":
                total = cost()
    finally:
        await gen.aclose()

    assert orch.verdict is not None and total is not None
    debater_turns = [_turn_info(t) for t in orch.turns if t.label != JUDGE_LABEL]
    judge_turns = [t for t in orch.turns if t.label == JUDGE_LABEL]
    judge = _turn_info(judge_turns[0]) if judge_turns else None
    return RunData(
        turns=debater_turns,
        judge=judge,
        verdict=orch.verdict.final_answer,
        judge_failed=bool(judge_turns and not judge_turns[0].valid),
        rounds_run=max((t.round for t in debater_turns), default=0),
        snapshots=snapshots,
        total=total,
    )


@dataclass
class Runner:
    agents: AgentsFile
    providers: dict[str, LLMProvider]  # already wrapped in CountingProvider
    dataset: Dataset
    settings: EvalSettings = field(default_factory=EvalSettings)

    def _orchestrator(self, q: Question, tag: str, rounds: int, min_critique: int) -> Orchestrator:
        return Orchestrator(
            debate_id=f"eval-{q.qid}-{tag}",
            question=self.dataset.prompt(q),
            mode="answer",
            rounds=rounds,
            agents=self.agents,
            providers=self.providers,
            seed=self.settings.seed,
            min_critique_rounds=min_critique,
        )

    async def run_question(self, q: Question) -> dict[str, Any]:
        """The full result record for one question. Raises QuestionAborted, stores nothing."""
        s = self.settings
        d = await drive(self._orchestrator(q, "d", s.rounds, s.d_min_critique), self.agents)
        c: RunData | None = None
        consistent = True
        if d.rounds_run > 1:
            c = await drive(self._orchestrator(q, "c", 1, 1), self.agents)
            consistent = prefix_consistent(d, c)

        results = derive(q.qid, s.seed, lambda a: self.dataset.score(q, a), d, c)
        facts = QuestionFacts(
            rounds_run=d.rounds_run,
            early_stopped=d.rounds_run < s.rounds,
            c_equals_d=c is None,
            prefix_consistent=consistent,
            cache_hits_d=d.total.cache_hits,
            truncated_turns=_truncated_turns(d, c),
        )
        return {
            "qid": q.qid,
            "question": q.text,
            "gold": self.dataset.gold_label(q),
            "meta": q.meta,
            "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "facts": asdict(facts),
            "conditions": {k: v.to_json() for k, v in results.items()},
            "turns": [asdict(t) for t in d.turns],
            "judge_d": asdict(d.judge) if d.judge else None,
            "judge_c": asdict(c.judge) if c and c.judge else None,
        }


def _truncated_turns(d: RunData, c: RunData | None) -> int:
    """Debater turns of run D plus judge turns of D (and C) that look cut off."""
    runs = [d] if c is None else [d, c]
    n = sum(t.truncated for t in d.turns)
    return n + sum(bool(r.judge and r.judge.truncated) for r in runs)


# --- a session over many questions ---


@dataclass
class SessionSummary:
    stop_reason: Literal["finished", "budget", "quota", "config", "interrupted"] = "finished"
    message: str = ""
    done_this_session: int = 0
    skipped: dict[str, str] = field(default_factory=dict)


Sleep = Callable[[float], Awaitable[None]]


async def run_session(
    *,
    runner: Runner,
    todo: list[Question],
    store: ResultStore,
    budget: Budget,
    sleep_s: float,
    sleep: Sleep = asyncio.sleep,
    progress: Callable[[str], None] = print,
    total_questions: int | None = None,
    already_done: int = 0,
) -> SessionSummary:
    summary = SessionSummary()
    agents, s = runner.agents, runner.settings
    estimate = {
        p: lo for p, (lo, _hi) in estimate_per_question(agents, s.rounds, s.d_min_critique).items()
    }
    total = total_questions or len(todo) + already_done

    for i, q in enumerate(todo):
        blocked = budget.can_start(estimate)
        if blocked:
            summary.stop_reason, summary.message = "budget", f"daily budget reached ({blocked})"
            return summary

        before = sum(budget.used(p) for p in estimate)
        record: dict[str, Any] | None = None
        last_error = ""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                record = await runner.run_question(q)
                break
            except QuestionAborted as e:
                if e.kind in ("budget", "quota", "config"):
                    summary.stop_reason = e.kind  # type: ignore[assignment]
                    where = f" ({e.provider})" if e.provider else ""
                    summary.message = _stop_message(e.kind, where, budget, str(e))
                    return summary
                last_error = str(e)
                progress(f"  {q.qid}: attempt {attempt}/{MAX_ATTEMPTS} failed: {last_error}")
        if record is None:
            summary.skipped[q.qid] = last_error
            store.write_skipped(summary.skipped)
            continue

        store.save_question(record)
        summary.done_this_session += 1
        progress(_progress_line(already_done + summary.done_this_session, total, record))
        spent = sum(budget.used(p) for p in estimate) - before
        if spent > 0 and sleep_s > 0 and i < len(todo) - 1:
            await sleep(sleep_s)  # spread token use; a fully cached question needs no pause
    return summary


def _stop_message(kind: str, where: str, budget: Budget, detail: str) -> str:
    if kind == "budget":
        reason = budget.tripped.reason if budget.tripped else detail
        return f"daily call budget reached ({reason})"
    if kind == "quota":
        return (
            f"a provider is rate-limited{where}; it may be the daily quota or a per-minute "
            "limit. Re-run later and finished questions will be skipped"
        )
    return f"provider configuration problem{where}: {detail}"


_SYMBOL = {"correct": "ok", "wrong": "no", "non_numeric": "nn", "missing": "ms"}


def _progress_line(done: int, total: int, rec: dict[str, Any]) -> str:
    marks = " ".join(f"{k}={_SYMBOL.get(v['status'], '?')}" for k, v in rec["conditions"].items())
    f = rec["facts"]
    return (
        f"[{done}/{total}] {rec['qid']} gold={rec['gold']} {marks} "
        f"rounds={f['rounds_run']} http={rec['conditions']['D']['cost']['api_calls']}"
    )


def wrap_providers(
    providers: dict[str, LLMProvider], agents: AgentsFile, budget: Budget
) -> dict[str, LLMProvider]:
    by_id: dict[str, AgentConfig] = {a.id: a for a in agents.all_agents()}
    return {
        agent_id: CountingProvider(p, budget, by_id[agent_id].provider)
        for agent_id, p in providers.items()
    }
