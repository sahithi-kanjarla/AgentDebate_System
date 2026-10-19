"""Admission control for POST /api/debates (FR10): per-IP limits, a global daily cap and a
concurrency cap, all protecting the free-tier quotas every visitor shares.

slowapi supplies the limiter, its in-memory storage and the moving-window strategy (from the
`limits` library). Its decorator is not used: it runs before the request body is parsed and
cannot skip or refund a hit, and a rerun that costs no provider calls must not count. So the
route decides what to charge and this module does the counting.
"""

import ipaddress
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from limits import RateLimitItemPerDay, RateLimitItemPerHour
from slowapi import Limiter

from app.core.settings import Settings

Scope = Literal["ip_hour", "ip_day", "global_day", "busy"]

BUSY_RETRY_AFTER_S = 30

_MESSAGES: dict[str, str] = {
    "ip_hour": "You have started the maximum number of debates for this hour.",
    "ip_day": "You have started the maximum number of debates for today.",
    "global_day": "The free model quota for this demo is used up for today.",
    "busy": "Several debates are running right now and the free models are busy.",
}


@dataclass(frozen=True)
class Denial:
    scope: Scope
    retry_after_s: int

    @property
    def message(self) -> str:
        return _MESSAGES[self.scope]

    def body(self) -> dict[str, object]:
        return {
            "error": "rate_limited",
            "scope": self.scope,
            "message": self.message,
            "retry_after_s": self.retry_after_s,
        }


class AdmissionDenied(Exception):
    def __init__(self, denial: Denial) -> None:
        super().__init__(denial.scope)
        self.denial = denial


def client_ip(peer: str | None, forwarded_for: str | None, trusted_hops: int) -> str:
    """The address to rate limit by.

    With no trusted proxy the socket peer is used and X-Forwarded-For is ignored, because any
    client can send that header. Behind N trusted proxies each one appends the address it saw, so
    the Nth entry from the right is the first one our own infrastructure vouches for; anything a
    client prepends sits to its left and is never read. A missing, short or malformed header falls
    back to the peer rather than trusting it.
    """
    fallback = peer or "unknown"
    if trusted_hops <= 0 or not forwarded_for:
        return fallback
    parts = [p.strip() for p in forwarded_for.split(",")]
    if len(parts) < trusted_hops:
        return fallback
    candidate = parts[-trusted_hops]
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return fallback


def seconds_until_utc_midnight(now: float) -> int:
    current = datetime.fromtimestamp(now, UTC)
    midnight = (current + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, math.ceil((midnight - current).total_seconds()))


def utc_midnight(now: float) -> datetime:
    """Start of the current UTC day (timezone-aware, as the `created_at` column expects)."""
    return datetime.fromtimestamp(now, UTC).replace(hour=0, minute=0, second=0, microsecond=0)


class AdmissionControl:
    def __init__(self, settings: Settings, clock: Callable[[], float] = time.time) -> None:
        self.settings = settings
        self._clock = clock
        self._limiter = Limiter(
            key_func=lambda: "unused", storage_uri="memory://", strategy="moving-window"
        )
        self._hour = RateLimitItemPerHour(settings.rate_limit_per_hour)
        self._day = RateLimitItemPerDay(settings.rate_limit_per_day)

    @property
    def enabled(self) -> bool:
        return self.settings.rate_limit_enabled

    @property
    def needs_global_count(self) -> bool:
        return self.enabled and self.settings.global_daily_cap > 0

    @property
    def now(self) -> float:
        return self._clock()

    def describe(self) -> str:
        """One line for the startup log, so a deployment cannot silently run unprotected."""
        s = self.settings
        if s.rate_limit_enabled:
            state = (
                f"rate limiting ON: {s.rate_limit_per_hour}/hour and {s.rate_limit_per_day}/day "
                f"per IP, global daily cap {s.global_daily_cap or 'off'}, "
                f"trusted proxy hops {s.trusted_proxy}"
            )
        else:
            state = "rate limiting OFF (set RATE_LIMIT_ENABLED=true for a public deployment)"
        cap = s.max_concurrent_debates or "off"
        return f"{state}; max concurrent debates {cap}"

    def _retry_after(self, item: RateLimitItemPerHour | RateLimitItemPerDay, ip: str) -> int:
        stats = self._limiter.limiter.get_window_stats(item, ip)
        return max(1, math.ceil(stats.reset_time - self.now))

    def admit(self, *, ip: str, exempt: bool, running: int, billable_today: int) -> None:
        """Raise AdmissionDenied, or count the request against the IP's limits and return.

        `exempt` requests (a rerun that costs no provider calls) skip the per-IP and global
        checks, but never the concurrency cap. Nothing is counted unless every check passes, so
        a refused request does not use up the IP's allowance.
        """
        s = self.settings
        charged = self.enabled and not exempt
        if charged:
            strategy = self._limiter.limiter
            windows: list[tuple[Scope, RateLimitItemPerHour | RateLimitItemPerDay]] = [
                ("ip_hour", self._hour),
                ("ip_day", self._day),
            ]
            for scope, item in windows:
                if not strategy.test(item, ip):
                    raise AdmissionDenied(Denial(scope, self._retry_after(item, ip)))
            if s.global_daily_cap > 0 and billable_today >= s.global_daily_cap:
                raise AdmissionDenied(Denial("global_day", seconds_until_utc_midnight(self.now)))
        if s.max_concurrent_debates > 0 and running >= s.max_concurrent_debates:
            raise AdmissionDenied(Denial("busy", BUSY_RETRY_AFTER_S))
        if charged:
            self._limiter.limiter.hit(self._hour, ip)
            self._limiter.limiter.hit(self._day, ip)
