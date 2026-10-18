"""Synchronous DB operations. Callers on the event loop must run these via asyncio.to_thread."""

from collections.abc import Sequence
from datetime import UTC
from typing import Any

from sqlalchemy.engine import Engine
from sqlmodel import Session, col, select

from app.db.models import Debate, DebateEventRow, Turn


def _session(engine: Engine) -> Session:
    return Session(engine, expire_on_commit=False)


def _iso(dt) -> str:
    return dt.replace(tzinfo=UTC).isoformat() if dt.tzinfo is None else dt.isoformat()


def create_debate(
    engine: Engine, *, debate_id: str, question: str, mode: str, config: dict[str, Any]
) -> None:
    with _session(engine) as s:
        s.add(Debate(id=debate_id, question=question, mode=mode, config_json=config))
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


def list_debates(engine: Engine, limit: int) -> list[dict[str, Any]]:
    with _session(engine) as s:
        rows = s.exec(select(Debate).order_by(col(Debate.created_at).desc()).limit(limit)).all()
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
