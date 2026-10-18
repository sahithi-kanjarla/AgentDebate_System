import random
import re
from collections.abc import Sequence
from dataclasses import dataclass

_LABEL_NUMBER = re.compile(r"(\d+)")


@dataclass(frozen=True)
class Anonymization:
    """What one recipient sees: its peers in a shuffled order labelled "Response 1..N".

    The mapping is kept server-side so critiques that name "Response 2" can be resolved back
    to the real agent (for critique_edge events and replay).
    """

    recipient: str
    order: tuple[str, ...]  # peer agent ids; order[i] is shown as "Response {i + 1}"

    @property
    def mapping(self) -> dict[str, str]:
        return {f"Response {i + 1}": agent for i, agent in enumerate(self.order)}

    def label_for(self, agent_id: str) -> str:
        return f"Response {self.order.index(agent_id) + 1}"

    def resolve(self, label: str) -> str | None:
        """Map a (possibly sloppy) label such as "response 2" back to an agent id."""
        match = _LABEL_NUMBER.search(label)
        if not match:
            return None
        index = int(match.group(1)) - 1
        return self.order[index] if 0 <= index < len(self.order) else None


def anonymize(recipient: str, peer_ids: Sequence[str], *, seed: int, round_: int) -> Anonymization:
    """Shuffle `peer_ids` for `recipient`; deterministic for the same (seed, round, recipient)."""
    peers = sorted(p for p in peer_ids if p != recipient)  # sorted: independent of input order
    random.Random(f"{seed}:{round_}:{recipient}").shuffle(peers)
    return Anonymization(recipient=recipient, order=tuple(peers))
