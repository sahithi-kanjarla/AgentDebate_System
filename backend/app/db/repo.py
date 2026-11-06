"""Synchronous DB operations. Callers on the event loop must run these via asyncio.to_thread."""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.engine import Engine
from sqlmodel import Session, col, select

from app.db.models import Debate, DebateEventRow, Turn


def _session(engine: Engine) -> Session:
    return Session(engine, expire_on_commit=False)


def _iso(dt) -> str:
    return dt.replace(tzinfo=UTC).isoformat() if dt.tzinfo is None else dt.isoformat()


def create_debate(
    engine: Engine,
    *,
    debate_id: str,
    question: str,
    mode: str,
    config: dict[str, Any],
    owner_hash: str | None = None,
) -> None:
    with _session(engine) as s:
        s.add(
            Debate(
                id=debate_id,
                question=question,
                mode=mode,
                config_json=config,
                owner_hash=owner_hash,
            )
        )
        s.commit()


def append_event(
    engine: Engine, debate_id: str, seq: int, type_: str, data: dict[str, Any]
) -> None:
    with _session(engine) as s:
        s.add(DebateEventRow(debate_id=debate_id, seq=seq, type=type_, data=data))
        s.commit()


def finish_debate(
    engine: Engine,
    debate_id: str,
    *,
    status: str,
    turns: Sequence[dict[str, Any]],
    verdict: dict[str, Any] | None,
    stats: dict[str, Any] | None,
) -> None:
    with _session(engine) as s:
        for t in turns:
            s.add(Turn(debate_id=debate_id, **t))
        debate = s.get(Debate, debate_id)
        if debate is not None:
            debate.status = status
            debate.verdict_json = verdict
            debate.stats_json = stats
            s.add(debate)
        s.commit()


def mark_interrupted(engine: Engine) -> int:
    """Debates still 'running' at startup were cut off by a restart; nothing is running them."""
    with _session(engine) as s:
        stuck = s.exec(select(Debate).where(Debate.status == "running")).all()
        for d in stuck:
            d.status = "interrupted"
            s.add(d)
        s.commit()
        return len(stuck)


def debate_exists(engine: Engine, debate_id: str) -> bool:
    with _session(engine) as s:
        return s.get(Debate, debate_id) is not None


def get_events(engine: Engine, debate_id: str, after_seq: int = -1) -> list[dict[str, Any]]:
    with _session(engine) as s:
        rows = s.exec(
            select(DebateEventRow)
            .where(DebateEventRow.debate_id == debate_id, DebateEventRow.seq > after_seq)
            .order_by(col(DebateEventRow.seq))
        ).all()
        return [{"seq": r.seq, "type": r.type, "data": r.data} for r in rows]


def get_debate(engine: Engine, debate_id: str) -> dict[str, Any] | None:
    with _session(engine) as s:
        d = s.get(Debate, debate_id)
        if d is None:
            return None
        turns = s.exec(select(Turn).where(Turn.debate_id == debate_id).order_by(col(Turn.id))).all()
        return {
            "id": d.id,
            "question": d.question,
            "mode": d.mode,
            "status": d.status,
            "created_at": _iso(d.created_at),
            "config": d.config_json,
            "verdict": d.verdict_json,
            "stats": d.stats_json,
            "turns": [t.model_dump(exclude={"debate_id", "id"}) | {"turn_id": t.id} for t in turns],
        }


def count_billable_since(engine: Engine, since: datetime) -> int:
    """Debates created since `since` that used (or may still use) provider calls.

    Running debates count. A finished debate that sent no HTTP request (every call answered from
    the response cache) does not; one with no recorded stats is counted, to stay on the safe side.
    """
    with _session(engine) as s:
        rows = s.exec(select(Debate).where(Debate.created_at >= since)).all()
        return sum(1 for d in rows if not _sent_no_requests(d))


def _sent_no_requests(d: Debate) -> bool:
    if d.status == "running" or not d.stats_json:
        return False
    return d.stats_json.get("api_calls") == 0


def find_replayable(
    engine: Engine, *, question: str, mode: str, config: dict[str, Any], limit: int = 5
) -> bool:
    """Is there a clean finished debate that a new one with this input and config would repeat
    entirely from the response cache?

    "Clean" means completed, same question (exact), mode and config (rounds, seed, early-stop
    setting and the lineup/prompt fingerprint), with no error events and no fallback, because a
    failed call is never cached and would be sent again. Legacy debates with no fingerprint never
    match. This errs toward "no", which only means the request is counted.
    """
    with _session(engine) as s:
        candidates = s.exec(
            select(Debate)
            .where(Debate.question == question, Debate.mode == mode, Debate.status == "completed")
            .order_by(col(Debate.created_at).desc())
            .limit(limit)
        ).all()
        for d in candidates:
            if any(d.config_json.get(k) != v for k, v in config.items()):
                continue
            if (d.stats_json or {}).get("fallbacks", 0):
                continue
            errored = s.exec(
                select(DebateEventRow.id).where(
                    DebateEventRow.debate_id == d.id, DebateEventRow.type == "error"
                )
            ).first()
            if errored is None:
                return True
        return False


def list_debates(engine: Engine, limit: int, owner_hash: str) -> list[dict[str, Any]]:
    """Only this owner's debates. Rows with no owner match nothing."""
    with _session(engine) as s:
        rows = s.exec(
            select(Debate)
            .where(Debate.owner_hash == owner_hash)
            .order_by(col(Debate.created_at).desc())
            .limit(limit)
        ).all()
        return [
            {
                "id": d.id,
                "question": d.question,
                "mode": d.mode,
                "status": d.status,
                "created_at": _iso(d.created_at),
                "final_answer": (d.verdict_json or {}).get("final_answer"),
                "confidence": (d.verdict_json or {}).get("confidence"),
            }
            for d in rows
        ]
