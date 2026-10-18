"""Synchronous response-cache operations. Run via asyncio.to_thread from async code."""

import hashlib
import json
from typing import Any

from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app.db.models import CacheEntry


def make_key(
    provider: str,
    model: str,
    params: dict[str, Any],
    messages: list[dict[str, str]],
    json_mode: bool,
) -> str:
    blob = json.dumps(
        {"p": provider, "m": model, "params": params, "msgs": messages, "json": json_mode},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(blob.encode()).hexdigest()


def get(engine: Engine, key: str) -> dict[str, Any] | None:
    with Session(engine, expire_on_commit=False) as s:
        row = s.get(CacheEntry, key)
        if row is None:
            return None
        return {
            "text": row.response_text,
            "tokens_in": row.tokens_in,
            "tokens_out": row.tokens_out,
            "provider": row.provider,
            "model": row.model,
        }


def put(
    engine: Engine,
    key: str,
    *,
    text: str,
    tokens_in: int,
    tokens_out: int,
    provider: str,
    model: str,
) -> None:
    try:
        with Session(engine, expire_on_commit=False) as s:
            s.merge(
                CacheEntry(
                    key_hash=key,
                    response_text=text,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    provider=provider,
                    model=model,
                )
            )
            s.commit()
    except IntegrityError:
        pass  # a concurrent writer stored the same key first; the entry is equivalent
