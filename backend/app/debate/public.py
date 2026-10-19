"""What the browser may see of a stored debate.

The database and the event log keep everything (provider, model, `label_map`). Anonymity is
enforced when serving: every debate-facing endpoint and the SSE stream (live and replayed) pass
through here, and the only way to learn who answered is the reveal endpoint, for debates that
are no longer running.
"""

from collections import Counter
from typing import Any

from app.schemas import DebateEvent

# Keys removed wherever they appear inside event data. None of them is a legitimate field of an
# event payload, so removing them recursively is safe and also covers payloads added later.
_HIDDEN_KEYS = frozenset({"label_map", "provider", "model"})
_HIDDEN_TURN_KEYS = frozenset({"provider", "model"})

REVEAL_NOTE = (
    "This only shows who wrote what. The debaters were never told each other's identity, "
    "and the model behind a persona does not change what the debate found."
)


def strip_hidden(value: Any) -> Any:
    """A copy of `value` with every hidden key removed, at any depth."""
    if isinstance(value, dict):
        return {k: strip_hidden(v) for k, v in value.items() if k not in _HIDDEN_KEYS}
    if isinstance(value, list):
        return [strip_hidden(v) for v in value]
    return value


def public_event(event: DebateEvent) -> DebateEvent:
    return event.model_copy(update={"data": strip_hidden(event.data)})


def public_event_row(row: dict[str, Any]) -> dict[str, Any]:
    return {**row, "data": strip_hidden(row["data"])}


def public_turn(turn: dict[str, Any]) -> dict[str, Any]:
    clean = {k: v for k, v in turn.items() if k not in _HIDDEN_TURN_KEYS}
    if clean.get("parsed_json") is not None:
        clean["parsed_json"] = strip_hidden(clean["parsed_json"])
    return clean


def public_debate(debate: dict[str, Any]) -> dict[str, Any]:
    """A stored debate as served by GET /api/debates/{id}."""
    out = dict(debate)
    out["turns"] = [public_turn(t) for t in debate.get("turns", [])]
    out["events"] = [public_event_row(e) for e in debate.get("events", [])]
    return out


def _entry(label: str, persona: str, turns: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(turns, key=lambda t: (t["round"], t.get("turn_id") or 0))
    rows = [
        {
            "round": t["round"],
            "provider": t["provider"],
            "model": t["model"],
            "fallback_used": bool(t["fallback_used"]),
            "valid": bool(t["valid"]),
        }
        for t in ordered
    ]
    # The model that answered most turns (ties go to the earliest), so a single fallback turn
    # does not rename the debater.
    pairs = [(r["provider"], r["model"]) for r in rows]
    counts = Counter(pairs)
    primary = max(counts, key=lambda pm: (counts[pm], -pairs.index(pm))) if counts else None
    return {
        "label": label,
        "persona": persona,
        "primary": {"provider": primary[0], "model": primary[1]} if primary else None,
        "turns": rows,
    }


def build_reveal(debate: dict[str, Any]) -> dict[str, Any]:
    """Who answered each turn, from stored turns. Only for debates that are not running."""
    by_label: dict[str, list[dict[str, Any]]] = {}
    for t in debate["turns"]:
        by_label.setdefault(t["agent_label"], []).append(t)
    debaters = [
        _entry(label, turns[0]["persona"], turns)
        for label, turns in by_label.items()
        if label != "Judge"
    ]
    judge_turns = by_label.get("Judge")
    return {
        "debate_id": debate["id"],
        "status": debate["status"],
        "debaters": sorted(debaters, key=lambda d: d["label"]),
        "judge": _entry("Judge", judge_turns[0]["persona"], judge_turns) if judge_turns else None,
        "note": REVEAL_NOTE,
    }
