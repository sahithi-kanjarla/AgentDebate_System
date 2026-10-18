import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.schemas import Cluster

_CURRENCY = re.compile(r"[$€£₹¥]")
_WRAPPERS = "\"'`*_ "
_TRAILING_PUNCT = ".!?;:,"


def normalize_answer(raw: str) -> str:
    """Canonical form so trivially different spellings of one answer cluster together.

    "42", "42.0", "$42" and "1,042.00" -> numbers; "Yes." and "yes" -> "yes".
    """
    s = re.sub(r"\s+", " ", raw).strip().strip(_WRAPPERS).casefold()
    s = s.rstrip(_TRAILING_PUNCT).strip(_WRAPPERS)
    numeric = _CURRENCY.sub("", s).replace(",", "").replace(" ", "")
    try:
        d = Decimal(numeric)
    except InvalidOperation:
        return s
    if not d.is_finite():
        return s
    return format(d.normalize(), "f")


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
    """Cluster agents by normalized final answer.

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
