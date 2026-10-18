"""Server-side derivations from recorded critiques: caught mistakes and received critiques.

Both are computed from what the debaters actually did (their critiques and answers), never from
the judge's or a debater's own account of it.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.debate.consensus import normalize_answer
from app.schemas import MistakeCaught


@dataclass(frozen=True)
class CritiqueRecord:
    """One critique a debater raised in `round`, already resolved to the target's label."""

    round: int
    critic: str
    target: str
    severity: str
    issue: str


def received_critiques(
    critiques: Sequence[CritiqueRecord], labels: Sequence[str]
) -> dict[str, list[dict[str, object]]]:
    """Critiques raised in one round, grouped by the agent whose previous answer they target.

    These are "critiques raised against the answer this agent revised". They are NOT a claim
    that they caused any change: agents do not see critiques addressed to them, only their
    peers' answers and reasoning. Every label gets a key (an empty list if nobody criticised it).
    """
    out: dict[str, list[dict[str, object]]] = {label: [] for label in labels}
    for c in critiques:
        out.setdefault(c.target, []).append(
            {"from_agent": c.critic, "issue": c.issue, "severity": c.severity, "round": c.round}
        )
    return out


def build_mistakes_caught(
    verdict_answer: str,
    critiques: Sequence[CritiqueRecord],
    answers: Mapping[int, Mapping[str, str]],
) -> list[MistakeCaught]:
    """The caught-mistakes list, from the recorded critiques and answers.

    `answers[round][label]` is the valid final answer an agent gave that round. A critique raised
    in round r counts when, comparing answers exactly (numbers by value, as for consensus):
      1. the target's answer before round r (its latest answer from rounds < r) differs from the
         verdict, and
      2. the critic's own round-r answer equals the verdict.
    It is attributed to the critic in round r. One entry per (target, wrong answer): the first
    critique in `critiques` order wins, so pass them in a deterministic order.
    """
    wanted = normalize_answer(verdict_answer)
    seen: set[tuple[str, str]] = set()
    caught: list[MistakeCaught] = []
    for c in critiques:
        critic_answer = answers.get(c.round, {}).get(c.critic)
        target_answer = _answer_before(answers, c.target, c.round)
        if critic_answer is None or target_answer is None or c.critic == c.target:
            continue
        if normalize_answer(critic_answer) != wanted:
            continue  # the critic was wrong (or undecided) at the time
        wrong = normalize_answer(target_answer)
        if wrong == wanted:
            continue  # the target held the verdict's answer: nothing to catch
        key = (c.target, wrong)
        if key in seen:
            continue
        seen.add(key)
        caught.append(MistakeCaught(description=c.issue, caught_by=c.critic, round=c.round))
    return caught


def _answer_before(answers: Mapping[int, Mapping[str, str]], label: str, rnd: int) -> str | None:
    for earlier in sorted((r for r in answers if r < rnd), reverse=True):
        if label in answers[earlier]:
            return answers[earlier][label]
    return None
