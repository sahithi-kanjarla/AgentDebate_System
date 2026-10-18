import asyncio
import logging
from typing import Any

from sqlalchemy.engine import Engine

from app.db import cache
from app.providers.base import CompletionResult, LLMProvider, Message

log = logging.getLogger(__name__)


class CachedProvider(LLMProvider):
    """Replays a stored reply for an identical request instead of calling the provider.

    Only successful completions are stored. A hit costs no quota and reports 0 ms latency.
    """

    def __init__(self, inner: LLMProvider, engine: Engine) -> None:
        self.inner = inner
        self._engine = engine
        self.name = inner.name
        self.model = inner.model

    def cache_params(self) -> dict[str, Any]:
        return self.inner.cache_params()

    async def is_reachable(self) -> bool:
        return await self.inner.is_reachable()

    async def complete(self, messages: list[Message], json_mode: bool = True) -> CompletionResult:
        key = cache.make_key(
            self.name,
            self.model,
            self.inner.cache_params(),
            [m.model_dump() for m in messages],
            json_mode,
        )
        try:
            hit = await asyncio.to_thread(cache.get, self._engine, key)
        except Exception:  # a broken cache must never break a debate
            log.exception("cache read failed")
            hit = None
        if hit is not None:
            log.info(
                "llm_call",
                extra={
                    "provider": self.name,
                    "model": self.model,
                    "status": "cached",
                    "latency_ms": 0,
                    "attempts": 0,
                    "retries": 0,
                    "tokens_in": hit["tokens_in"],
                    "tokens_out": hit["tokens_out"],
                },
            )
            return CompletionResult(
                text=hit["text"],
                tokens_in=hit["tokens_in"],
                tokens_out=hit["tokens_out"],
                latency_ms=0,
                provider=self.name,
                model=self.model,
                attempts=0,
                cached=True,
            )

        result = await self.inner.complete(messages, json_mode)
        try:
            await asyncio.to_thread(
                cache.put,
                self._engine,
                key,
                text=result.text,
                tokens_in=result.tokens_in,
                tokens_out=result.tokens_out,
                provider=self.name,
                model=self.model,
            )
        except Exception:
            log.exception("cache write failed")
        return result
