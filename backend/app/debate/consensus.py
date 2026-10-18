import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from app.schemas import Cluster

_CURRENCY = "$€£₹¥"
# A pure number: optional currency symbol, optional sign, digits (thousands commas only in
# proper groups of three, so "1,2,3" is a list and never 123), optional decimals. fullmatch means
# no surrounding whitespace, no trailing period, no words: "42." and " 42" are plain text.
_NUMBER = re.compile(
    rf"[{_CURRENCY}]?[+-]?(?:(?:[0-9]{{1,3}}(?:,[0-9]{{3}})+|[0-9]+)(?:\.[0-9]+)?|\.[0-9]+)"
)


def normalize_answer(raw: str) -> str:
    """The key two answers are compared by. Exact, except that pure numbers compare by value.

    Everything else (case, whitespace, punctuation, indentation) can be meaningful, e.g. Python
    prints "[1, 2]" and not "[1,2]", so text is returned untouched. A pure number is
    canonicalised so "42", "42.0", "$42" and "1,042" / "1042" cluster together.
    """
    if _NUMBER.fullmatch(raw) is None:
        return raw
    digits = raw.lstrip(_CURRENCY).replace(",", "")
    return format(Decimal(digits).normalize(), "f")


class ClusterIds:
    """Stable cluster ids for one debate, so an answer keeps its colour across rounds."""

    def __init__(self) -> None:
        self._ids: dict[str, int] = {}

    def id_for(self, normalized: str) -> int:
        return self._ids.setdefault(normalized, len(self._ids))


@dataclass
class RoundConsensus:
    clusters: list[Cluster]
    score: float  # largest cluster / total debaters, e.g. 2/3
    agreed: bool  # all valid answers match, and at least two agents gave one


def compute_consensus(
    answers: Mapping[str, str | None], ids: ClusterIds, total: int | None = None
) -> RoundConsensus:
    """Cluster agents by exact final answer (numbers by value, see `normalize_answer`).

    `answers` maps agent label -> final answer, or None when the agent produced no valid answer
    this round (it cannot agree with anyone, but it still counts in the denominator).
    """
    total = len(answers) if total is None else total
    groups: dict[str, list[str]] = {}
    for agent, answer in answers.items():
        if answer is None:
            continue
        groups.setdefault(normalize_answer(answer), []).append(agent)
    clusters = [
        Cluster(cluster_id=ids.id_for(norm), normalized_answer=norm, agents=agents)
        for norm, agents in groups.items()
    ]
    largest = max((len(c.agents) for c in clusters), default=0)
    return RoundConsensus(
        clusters=clusters,
        score=largest / total if total else 0.0,
        agreed=len(clusters) == 1 and largest >= 2,
    )
