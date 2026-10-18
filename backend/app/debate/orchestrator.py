import asyncio
import hashlib
import json
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from app.core.logging import agent_var
from app.core.settings import AgentConfig, AgentsFile
from app.debate.anonymize import Anonymization, anonymize
from app.debate.consensus import ClusterIds, RoundConsensus, compute_consensus, normalize_answer
from app.debate.parsing import ParseOutcome, parse_with_repair
from app.debate.prompts import mode_task, render_messages
from app.providers.base import LLMProvider, Message, ProviderError
from app.schemas import DebaterOutput, EventType, JudgeOutput, Mode

log = logging.getLogger(__name__)

Event = tuple[EventType, dict[str, Any]]


@dataclass
class TurnRecord:
    """Everything persisted per agent turn (maps onto the `Turn` table)."""

    round: int
    agent_id: str
    label: str
    persona: str
    provider: str
    model: str
    prompt_hash: str
    raw_text: str
    parsed_json: dict[str, Any] | None
    valid: bool
    tokens_in: int
    tokens_out: int
    latency_ms: int
    fallback_used: bool = False
    error: str | None = None


@dataclass
class _Outcome:
    cfg: AgentConfig
    round: int
    prompt_hash: str
    anon: Anonymization | None
    parsed: ParseOutcome[DebaterOutput] | None = None
    error: str | None = None
    recoverable: bool = True


@dataclass
class _Stats:
    calls: int = 0
    tokens: int = 0
    api_calls: int = 0
    cache_hits: int = 0
    fallbacks: int = 0

    def add(self, parsed: ParseOutcome[Any]) -> None:
        self.calls += parsed.calls
        self.tokens += parsed.tokens_in + parsed.tokens_out
        self.api_calls += parsed.api_calls
        self.cache_hits += parsed.cache_hits
        self.fallbacks += int(parsed.fallback_used)


@dataclass
class _RoundLog:
    round: int
    # label -> (output, resolved critiques as (target label, severity, issue))
    entries: dict[str, tuple[DebaterOutput, list[tuple[str, str, str]]]] = field(
        default_factory=dict
    )


def _hash_messages(messages: list[Message]) -> str:
    blob = json.dumps([m.model_dump() for m in messages], sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


class Orchestrator:
    """Runs one debate and yields its SSE events in order as `(type, data)` tuples.

    Agents within a round run concurrently and each is isolated: a failing agent produces an
    `error` event and an invalid turn, never a cancelled round. After `run()` finishes,
    `turns`, `verdict` and `stats` hold what the persistence layer needs.
    """

    def __init__(
        self,
        *,
        debate_id: str,
        question: str,
        mode: Mode,
        rounds: int,
        agents: AgentsFile,
        providers: dict[str, LLMProvider],
        seed: int,
        min_critique_rounds: int = 1,
    ) -> None:
        self.debate_id = debate_id
        self.question = question
        self.mode = mode
        self.rounds = rounds
        self.agents = agents
        self.providers = providers
        self.seed = seed
        # Never stop before this many critique rounds, even if round 0 is unanimous.
        self.min_critique_rounds = min(min_critique_rounds, rounds)

        self.labels = {cfg.id: f"Debater {i + 1}" for i, cfg in enumerate(agents.debaters)}
        self.turns: list[TurnRecord] = []
        self.verdict: JudgeOutput | None = None
        self.stats = _Stats()
        self.elapsed_ms = 0

        self._latest: dict[str, DebaterOutput] = {}
        self._cluster_ids = ClusterIds()
        self._history: list[_RoundLog] = []
        self._last_consensus: RoundConsensus | None = None

    # --- public ---

    async def run(self) -> AsyncIterator[Event]:
        started = time.monotonic()
        yield (
            "debate_started",
            {
                "id": self.debate_id,
                "agents": [
                    {"label": self.labels[c.id], "persona": c.persona} for c in self.agents.debaters
                ],
            },
        )
        last_round = 0
        for rnd in range(self.rounds + 1):  # round 0 = independent answers
            last_round = rnd
            async for event in self._run_round(rnd):
                yield event
            agreed = bool(self._last_consensus and self._last_consensus.agreed)
            if agreed and rnd >= self.min_critique_rounds:
                break

        async for event in self._run_judge(last_round + 1):
            yield event

        self.elapsed_ms = int((time.monotonic() - started) * 1000)
        yield (
            "done",
            {
                "stats": {
                    "total_tokens": self.stats.tokens,
                    "latency_ms": self.elapsed_ms,
                    "calls": self.stats.calls,
                    "api_calls": self.stats.api_calls,
                    "cache_hits": self.stats.cache_hits,
                    "fallbacks": self.stats.fallbacks,
                }
            },
        )

    # --- rounds ---

    async def _run_round(self, rnd: int) -> AsyncIterator[Event]:
        for cfg in self.agents.debaters:
            yield "agent_thinking", {"round": rnd, "agent": self.labels[cfg.id]}

        # Snapshot peers before launching so every agent sees the same previous-round state.
        latest = dict(self._latest)
        tasks = [asyncio.create_task(self._turn(cfg, rnd, latest)) for cfg in self.agents.debaters]
        round_log = _RoundLog(round=rnd)
        answers: dict[str, str | None] = {self.labels[c.id]: None for c in self.agents.debaters}
        new_latest: dict[str, DebaterOutput] = {}
        try:
            for finished in asyncio.as_completed(tasks):
                outcome = await finished
                for event in self._handle_outcome(outcome, round_log, answers, new_latest):
                    yield event
        finally:
            for t in tasks:
                t.cancel()  # only matters if the consumer abandons the stream mid-round

        self._latest.update(new_latest)
        self._history.append(round_log)
        consensus = compute_consensus(answers, self._cluster_ids)
        self._last_consensus = consensus
        yield (
            "round_complete",
            {
                "round": rnd,
                "consensus_score": consensus.score,
                "agreed": consensus.agreed,
                "clusters": [c.model_dump() for c in consensus.clusters],
            },
        )

    async def _turn(self, cfg: AgentConfig, rnd: int, latest: dict[str, DebaterOutput]) -> _Outcome:
        """One agent's turn. Never raises (except cancellation): failures become the outcome."""
        agent_var.set(self.labels[cfg.id])  # log context for this agent's task
        anon: Anonymization | None = None
        messages: list[Message] = []
        try:
            if rnd == 0:
                messages = render_messages(
                    "debater",
                    persona=cfg.persona,
                    persona_prompt=cfg.persona_prompt,
                    mode=self.mode,
                    task=mode_task(self.mode),
                    question=self.question,
                )
            else:
                peers = [a for a in latest if a != cfg.id]
                anon = anonymize(cfg.id, peers, seed=self.seed, round_=rnd)
                messages = render_messages(
                    "critique",
                    persona=cfg.persona,
                    persona_prompt=cfg.persona_prompt,
                    mode=self.mode,
                    task=mode_task(self.mode),
                    question=self.question,
                    round=rnd,
                    own_previous=self._own_previous(cfg.id, latest),
                    peers=self._render_peers(anon, latest),
                )
            outcome = _Outcome(cfg, rnd, _hash_messages(messages), anon)
            outcome.parsed = await parse_with_repair(
                self.providers[cfg.id], messages, DebaterOutput
            )
            if outcome.parsed.value is None:
                outcome.error = f"invalid output after repair: {outcome.parsed.error}"
            return outcome
        except ProviderError as e:
            return _Outcome(
                cfg, rnd, _hash_messages(messages), anon, error=str(e), recoverable=e.recoverable
            )
        except Exception as e:  # noqa: BLE001 - one agent must never take down the round
            log.exception("agent %s crashed in round %d", cfg.id, rnd)
            return _Outcome(
                cfg, rnd, _hash_messages(messages), anon, error=f"{type(e).__name__}: {e}"
            )

    def _handle_outcome(
        self,
        outcome: _Outcome,
        round_log: _RoundLog,
        answers: dict[str, str | None],
        new_latest: dict[str, DebaterOutput],
    ) -> list[Event]:
        cfg, label, rnd = outcome.cfg, self.labels[outcome.cfg.id], outcome.round
        parsed = outcome.parsed
        if parsed:
            self.stats.add(parsed)

        record = TurnRecord(
            round=rnd,
            agent_id=cfg.id,
            label=label,
            persona=cfg.persona,
            provider=(parsed.provider if parsed else "") or cfg.provider,
            model=(parsed.model if parsed else "") or cfg.model,
            prompt_hash=outcome.prompt_hash,
            raw_text=parsed.raw_text if parsed else "",
            parsed_json=None,
            valid=False,
            tokens_in=parsed.tokens_in if parsed else 0,
            tokens_out=parsed.tokens_out if parsed else 0,
            latency_ms=parsed.latency_ms if parsed else 0,
            fallback_used=bool(parsed and parsed.fallback_used),
            error=outcome.error,
        )
        if parsed is None or parsed.value is None:
            message = outcome.error or "agent produced no output"
            payload = {"valid": False, "error": message}
            record.parsed_json = payload
            self.turns.append(record)
            return [
                ("agent_response", {"round": rnd, "agent": label, "payload": payload}),
                ("error", {"agent": label, "message": message, "recoverable": outcome.recoverable}),
            ]

        out = parsed.value
        answers[label] = out.final_answer
        new_latest[cfg.id] = out
        cluster_id = self._cluster_ids.id_for(normalize_answer(out.final_answer))

        critiques: list[dict[str, Any]] = []
        edges: list[Event] = []
        resolved: list[tuple[str, str, str]] = []
        for c in out.critiques:
            target_id = outcome.anon.resolve(c.target) if outcome.anon else None
            target_label = self.labels[target_id] if target_id else None
            critiques.append({**c.model_dump(), "target_agent": target_label})
            if target_label:
                resolved.append((target_label, c.severity, c.issue))
                edges.append(
                    (
                        "critique_edge",
                        {
                            "round": rnd,
                            "from_agent": label,
                            "to_agent": target_label,
                            "severity": c.severity,
                            "issue": c.issue,
                        },
                    )
                )
        round_log.entries[label] = (out, resolved)

        payload = {
            **out.model_dump(),
            "critiques": critiques,
            "valid": True,
            "cluster_id": cluster_id,
            "fallback_used": parsed.fallback_used,
            "label_map": {k: self.labels[v] for k, v in outcome.anon.mapping.items()}
            if outcome.anon
            else {},
        }
        record.parsed_json = payload
        record.valid = True
        self.turns.append(record)
        return [("agent_response", {"round": rnd, "agent": label, "payload": payload}), *edges]

    # --- prompt pieces ---

    def _own_previous(self, agent_id: str, latest: dict[str, DebaterOutput]) -> str:
        own = latest.get(agent_id)
        if own is None:
            return "You gave no valid answer in the previous round."
        return f"Your previous answer: {own.final_answer} (confidence {own.confidence})."

    @staticmethod
    def _render_peers(anon: Anonymization, latest: dict[str, DebaterOutput]) -> str:
        if not anon.order:
            return "(no other responses are available)"
        blocks = []
        for i, agent_id in enumerate(anon.order, start=1):
            peer = latest[agent_id]
            blocks.append(
                f"Response {i}:\nFinal answer: {peer.final_answer}\n"
                f"Confidence: {peer.confidence}\nReasoning: {peer.reasoning}"
            )
        return "\n\n".join(blocks)

    # --- judge ---

    def _transcript(self) -> str:
        lines: list[str] = []
        for rl in self._history:
            title = "Independent answers" if rl.round == 0 else f"Critique round {rl.round}"
            lines.append(f"== Round {rl.round}: {title} ==")
            # Fixed debater order, not completion order: the prompt (and so the cache key)
            # must not depend on which provider happened to answer first.
            for label in self.labels.values():
                if label not in rl.entries:
                    continue
                out, critiques = rl.entries[label]
                lines.append(
                    f"{label}: final answer {out.final_answer} (confidence {out.confidence})"
                )
                lines.append(f"  Reasoning: {out.reasoning}")
                for target, severity, issue in critiques:
                    lines.append(f"  Critique of {target} [{severity}]: {issue}")
                if out.changed_mind:
                    lines.append(f"  Changed mind because: {out.changed_mind_because}")
            lines.append("")
        return "\n".join(lines).strip()

    async def _run_judge(self, rnd: int) -> AsyncIterator[Event]:
        judge = self.agents.judge
        agent_var.set("Judge")
        messages = render_messages(
            "judge",
            persona_prompt=judge.persona_prompt,
            mode=self.mode,
            task=mode_task(self.mode),
            question=self.question,
            transcript=self._transcript(),
        )
        yield "agent_thinking", {"round": rnd, "agent": "Judge"}
        error: str | None = None
        recoverable = True
        parsed: ParseOutcome[JudgeOutput] | None = None
        try:
            parsed = await parse_with_repair(self.providers[judge.id], messages, JudgeOutput)
            if parsed.value is None:
                error = f"judge output invalid after repair: {parsed.error}"
        except ProviderError as e:
            error, recoverable = str(e), e.recoverable
        except Exception as e:  # noqa: BLE001
            log.exception("judge crashed")
            error = f"{type(e).__name__}: {e}"

        if parsed:
            self.stats.add(parsed)
        if parsed and parsed.value:
            self.verdict = parsed.value
        else:
            yield "error", {"agent": "Judge", "message": error, "recoverable": recoverable}
            self.verdict = self._fallback_verdict(error or "judge unavailable")

        self.turns.append(
            TurnRecord(
                round=rnd,
                agent_id=judge.id,
                label="Judge",
                persona=judge.persona,
                provider=(parsed.provider if parsed else "") or judge.provider,
                model=(parsed.model if parsed else "") or judge.model,
                prompt_hash=_hash_messages(messages),
                raw_text=parsed.raw_text if parsed else "",
                parsed_json=self.verdict.model_dump(),
                valid=bool(parsed and parsed.value),
                tokens_in=parsed.tokens_in if parsed else 0,
                tokens_out=parsed.tokens_out if parsed else 0,
                latency_ms=parsed.latency_ms if parsed else 0,
                fallback_used=bool(parsed and parsed.fallback_used),
                error=error,
            )
        )
        yield "judge_verdict", {"payload": self.verdict.model_dump()}

    def _fallback_verdict(self, reason: str) -> JudgeOutput:
        """Majority verdict used when the judge is unavailable, so a debate still ends cleanly."""
        cons = self._last_consensus
        if not cons or not cons.clusters:
            return JudgeOutput(
                final_answer="No valid answer",
                confidence=0,
                summary=f"No debater produced a valid answer and the judge failed ({reason}).",
                consensus_reached=False,
            )
        top = max(cons.clusters, key=lambda c: len(c.agents))
        ids = {label: aid for aid, label in self.labels.items()}
        members = [self._latest[ids[a]] for a in top.agents if ids[a] in self._latest]
        mean_conf = sum(m.confidence for m in members) / len(members)
        return JudgeOutput(
            final_answer=members[0].final_answer,
            confidence=int(mean_conf * cons.score),
            summary=(
                f"The judge was unavailable ({reason}); this is the majority answer from the "
                f"last round ({len(top.agents)} of {len(self.labels)} debaters)."
            ),
            dissent=None if cons.agreed else "Debaters did not fully agree.",
            consensus_reached=cons.agreed,
        )
