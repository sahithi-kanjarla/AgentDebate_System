import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.providers.base import ProviderError

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_s: float = 1.0
    max_delay_s: float = 8.0
    # A server asking us to wait longer than this (e.g. a spent daily quota) is not worth
    # waiting for: give up on this provider so the fallback chain can take over.
    max_retry_after_s: float = 30.0

    def backoff(self, attempt: int, rng: random.Random) -> float:
        """Exponential backoff with full jitter: uniform(0, min(cap, base * 2^(attempt-1)))."""
        return rng.uniform(0, min(self.max_delay_s, self.base_delay_s * 2 ** (attempt - 1)))


class RateLimiter:
    """Spaces calls at least 60/rpm seconds apart (shared by every model of one provider).

    Slots are reserved in arrival order, so concurrent callers queue instead of bursting.
    """

    def __init__(
        self,
        rpm: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.interval_s = 60.0 / rpm
        self._clock = clock
        self._sleep = sleep
        self._next_slot = 0.0

    async def wait(self) -> None:
        now = self._clock()
        slot = max(now, self._next_slot)  # no await between read and write: slots never collide
        self._next_slot = slot + self.interval_s
        if slot > now:
            await self._sleep(slot - now)


async def call_with_retries[T](
    op: Callable[[], Awaitable[T]],
    policy: RetryPolicy,
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    rng: random.Random | None = None,
    label: str = "",
) -> tuple[T, int]:
    """Run `op`, retrying retryable ProviderErrors. Returns (result, attempts_used).

    On failure raises the last ProviderError with `.attempts` set.
    """
    rng = rng or random.Random()
    attempt = 0
    while True:
        attempt += 1
        try:
            return await op(), attempt
        except ProviderError as e:
            e.attempts = attempt
            if not e.retryable or attempt >= policy.max_attempts:
                raise
            if e.retry_after is not None:
                if e.retry_after > policy.max_retry_after_s:
                    raise
                delay = e.retry_after
            else:
                delay = policy.backoff(attempt, rng)
            log.warning(
                "llm_retry",
                extra={
                    "provider": label,
                    "attempt": attempt,
                    "delay_s": round(delay, 3),
                    "error_category": e.category,
                    "http_status": e.status,
                },
            )
            await sleep(delay)
