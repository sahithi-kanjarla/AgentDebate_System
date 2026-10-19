"""Derive every condition from the recorded runs of one question. Pure functions, no I/O.

    A1..A3  each debater's round-0 answer (one call each)
    B       majority of the three round-0 answers (self-consistency control, no debate)
    C       judge's answer after 1 critique round   (a second run whose rounds 0-1 are cache hits)
    D       judge's answer after up to 3 rounds     (the app's normal early stop applies)
    D_vote  plurality of the last round's answers, no judge (diagnostic: debate without a judge)

Costs come from the fresh run D, never from cached replays (a cache hit reports 0 ms latency).
"""

import random
from collections.abc import Callable
from dataclasses import asdict, dataclass, field

from app.debate.consensus import normalize_answer
from eval.scoring import Score

JUDGE_LABEL = "Judge"


@dataclass(frozen=True)
class Cost:
    calls: int = 0  # logical calls, repairs included
    api_calls: int = 0  # HTTP requests actually sent (cache hits excluded)
    tokens: int = 0
    latency_ms: int = 0
    cache_hits: int = 0

    def __add__(self, o: "Cost") -> "Cost":
        return Cost(*(a + b for a, b in zip(self.tuple(), o.tuple(), strict=True)))

    def __sub__(self, o: "Cost") -> "Cost":
        return Cost(*(a - b for a, b in zip(self.tuple(), o.tuple(), strict=True)))

    def tuple(self) -> tuple[int, int, int, int, int]:
        return (self.calls, self.api_calls, self.tokens, self.latency_ms, self.cache_hits)


@dataclass
class TurnInfo:
    round: int
    label: str  # "Debater 1".. or "Judge"
    persona: str
    provider: str
    model: str
    fallback_used: bool
    valid: bool
    answer: str | None
    confidence: int | None
    tokens_in: int
    tokens_out: int
    latency_ms: int
    truncated: bool = False  # invalid, and the output looks cut off
    # Diagnosis aids, so a bad turn can be understood without the response cache.
    finish_reason: str | None = None  # None: cached replay or provider did not say
    raw_tail: str = ""  # last 300 characters of the last reply
    repair_used: bool = False
    error: str | None = None  # provider error text, e.g. empty_response (finish_reason=length)


@dataclass
class RunData:
    """What one orchestrator run recorded."""

    turns: list[TurnInfo]  # debater turns only
    judge: TurnInfo | None
    verdict: str
    judge_failed: bool  # judge output unusable, so the verdict is the orchestrator's majority
    rounds_run: int  # last debate round that ran (0 = independent answers only)
    snapshots: dict[int, Cost]  # cumulative cost after each round, judge excluded
    total: Cost  # whole run, judge included

    def used_fallback(self, up_to_round: int | None = None, judge: bool = True) -> bool:
        turns = [t for t in self.turns if up_to_round is None or t.round <= up_to_round]
        if judge and self.judge is not None:
            turns.append(self.judge)
        return any(t.fallback_used for t in turns)


@dataclass
class ConditionResult:
    answer: str | None
    status: str
    correct: bool
    fallback: bool  # any contributing turn was answered by a fallback model
    cost: Cost
    note: str | None = None  # "tie", "judge_failed", "no_valid_answers"
    truncated: bool = False  # the answer is missing because its source output was cut off

    def to_json(self) -> dict:
        d = asdict(self)
        d["cost"] = asdict(self.cost)
        return d


def majority(answers: list[str | None], salt: str) -> tuple[str | None, bool]:
    """Most common answer by the app's exact comparison. Returns (answer, tied).

    Invalid/missing answers do not vote. On a tie the pick is a seeded random choice among the
    leading answers (deterministic for a given salt) and `tied` is True.
    """
    groups: dict[str, list[str]] = {}
    for a in answers:
        if a is not None:
            groups.setdefault(normalize_answer(a), []).append(a)
    if not groups:
        return None, False
    top = max(len(v) for v in groups.values())
    leaders = [v for v in groups.values() if len(v) == top]
    if len(leaders) == 1:
        return leaders[0][0], False
    return random.Random(salt).choice(leaders)[0], True


def _answers(run: RunData, rnd: int) -> list[str | None]:
    return [t.answer for t in run.turns if t.round == rnd]


def prefix_consistent(d: RunData, c: RunData, up_to_round: int = 1) -> bool:
    """Did the C run see the same debater answers as D in rounds 0..up_to_round?"""

    def key(run: RunData) -> list[tuple[int, str, str | None]]:
        return sorted((t.round, t.label, t.answer) for t in run.turns if t.round <= up_to_round)

    return key(d) == key(c)


def _judge_cut_off(run: RunData) -> bool:
    return bool(run.judge_failed and run.judge and run.judge.truncated)


def derive(
    qid: str,
    seed: int,
    score: Callable[[str | None], Score],
    d: RunData,
    c: RunData | None,
) -> dict[str, ConditionResult]:
    """All conditions for one question. `c` is None when D stopped after round 1, in which case
    C's transcript (and so its judge prompt) is identical to D's and C == D."""

    def result(
        answer: str | None,
        cost: Cost,
        fallback: bool,
        note: str | None = None,
        truncated: bool = False,
    ) -> ConditionResult:
        s = score(answer)
        return ConditionResult(answer, s.status, s.correct, fallback, cost, note, truncated)

    out: dict[str, ConditionResult] = {}

    round0 = sorted((t for t in d.turns if t.round == 0), key=lambda t: t.label)
    for i, t in enumerate(round0, start=1):
        # One call each. repair calls are not separable per turn, so calls is nominal.
        cost = Cost(1, 1, t.tokens_in + t.tokens_out, t.latency_ms, 0)
        out[f"A{i}"] = result(t.answer, cost, t.fallback_used, truncated=t.truncated)

    pick, tied = majority(_answers(d, 0), f"{seed}:{qid}:B")
    note = "tie" if tied else ("no_valid_answers" if pick is None else None)
    out["B"] = result(pick, d.snapshots[0], d.used_fallback(0, judge=False), note)

    if c is None:
        out["C"] = result(
            d.verdict,
            d.total,
            d.used_fallback(),
            "judge_failed" if d.judge_failed else None,
            _judge_cut_off(d),
        )
    else:
        last = max(c.snapshots)
        judge_cost = c.total - c.snapshots[last]
        out["C"] = result(
            c.verdict,
            d.snapshots[1] + judge_cost,
            d.used_fallback(1, judge=False) or bool(c.judge and c.judge.fallback_used),
            "judge_failed" if c.judge_failed else None,
            _judge_cut_off(c),
        )

    out["D"] = result(
        d.verdict,
        d.total,
        d.used_fallback(),
        "judge_failed" if d.judge_failed else None,
        _judge_cut_off(d),
    )

    vote, vtied = majority(_answers(d, d.rounds_run), f"{seed}:{qid}:Dvote")
    vnote = "tie" if vtied else ("no_valid_answers" if vote is None else None)
    out["D_vote"] = result(
        vote, d.snapshots[d.rounds_run], d.used_fallback(d.rounds_run, judge=False), vnote
    )
    return out


@dataclass
class QuestionFacts:
    """Per-question facts that are not a condition (rounds run, early stop, consistency)."""

    rounds_run: int
    early_stopped: bool
    c_equals_d: bool
    prefix_consistent: bool
    cache_hits_d: int
    truncated_turns: int = 0  # turns whose output looks cut off by the token limit
    extra: dict = field(default_factory=dict)
