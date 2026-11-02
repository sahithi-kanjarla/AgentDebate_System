"""Quota awareness: per-provider and global daily call caps, a ledger that survives restarts, and
a provider wrapper that counts real HTTP requests (cache hits are free).

The default caps are deliberately conservative guesses, because the free-tier limits are not
verified. Replace them with measured numbers after the pilot.
"""

import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from app.core.settings import AgentsFile
from app.providers.base import CompletionResult, LLMProvider, Message, ProviderError

DEFAULT_PROVIDER_CAPS: dict[str, int] = {
    "openrouter": 40,
    "groq": 500,
    "gemini": 200,
    "mistral": 200,
}
# Seconds between questions. Groq's gpt-oss free tier is about 8K tokens per minute per model
# (unverified) and one question puts roughly 6 to 8K tokens through each Groq model.
DEFAULT_SLEEP_BETWEEN_S = 60.0


def utc_today() -> str:
    return datetime.now(UTC).date().isoformat()


def parse_caps(text: str) -> dict[str, int]:
    """'openrouter=40,groq=500' -> {...}. 0 means no cap for that provider."""
    caps: dict[str, int] = {}
    for part in filter(None, (p.strip() for p in text.split(","))):
        name, sep, value = part.partition("=")
        if not sep or not name.strip() or not value.strip().isdigit():
            raise ValueError(f"bad cap {part!r}; expected provider=number")
        caps[name.strip()] = int(value)
    return caps


class BudgetExhausted(ProviderError):
    """A call was refused because a daily cap is reached. Never sent to a provider."""

    def __init__(self, provider: str, reason: str) -> None:
        super().__init__("budget_exhausted", recoverable=False, category="budget_exhausted")
        self.provider = provider
        self.reason = reason
        self.attempts = 0


class Ledger:
    """HTTP requests spent per UTC day per provider, saved after every change."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.days: dict[str, dict[str, int]] = {}
        if path.exists():
            try:
                self.days = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.days = {}

    def used(self, day: str, provider: str | None = None) -> int:
        counts = self.days.get(day, {})
        return counts.get(provider, 0) if provider else sum(counts.values())

    def add(self, day: str, provider: str, n: int) -> None:
        if n <= 0:
            return
        counts = self.days.setdefault(day, {})
        counts[provider] = counts.get(provider, 0) + n
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.days, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.path)


class Budget:
    def __init__(
        self,
        ledger: Ledger,
        *,
        provider_caps: dict[str, int] | None = None,
        daily_cap: int | None = None,
        today: Callable[[], str] = utc_today,
    ) -> None:
        self.ledger = ledger
        self.caps = {p: c for p, c in (provider_caps or {}).items() if c > 0}
        self.daily_cap = daily_cap if daily_cap and daily_cap > 0 else None
        self.today = today
        self.tripped: BudgetExhausted | None = None

    def used(self, provider: str | None = None) -> int:
        return self.ledger.used(self.today(), provider)

    def reason_blocked(self, provider: str) -> str | None:
        """Why one more call to `provider` would break a cap, else None."""
        cap = self.caps.get(provider)
        if cap is not None and self.used(provider) >= cap:
            return f"{provider} daily cap {cap} reached"
        if self.daily_cap is not None and self.used() >= self.daily_cap:
            return f"global daily cap {self.daily_cap} reached"
        return None

    def check(self, provider: str) -> None:
        """Called before every call. Once tripped, every later call is refused too, so
        concurrent agents of the same question stop together."""
        if self.tripped is None:
            reason = self.reason_blocked(provider)
            if reason:
                self.tripped = BudgetExhausted(provider, reason)
        if self.tripped is not None:
            raise self.tripped

    def record(self, provider: str, n: int) -> None:
        self.ledger.add(self.today(), provider, n)

    def can_start(self, estimate: dict[str, int]) -> str | None:
        """None if a question needing at least `estimate` calls fits; else why it does not."""
        for provider, need in estimate.items():
            cap = self.caps.get(provider)
            if cap is not None and self.used(provider) + need > cap:
                return f"{provider}: {self.used(provider)} used today + {need} needed > cap {cap}"
        if self.daily_cap is not None and self.used() + sum(estimate.values()) > self.daily_cap:
            need = sum(estimate.values())
            return f"global: {self.used()} used today + {need} needed > cap {self.daily_cap}"
        return None


class CountingProvider(LLMProvider):
    """Counts HTTP requests per provider against the budget. A cache hit has attempts == 0, so
    it costs nothing. With fallbacks on, counts are attributed to the answering provider and
    failed legs are approximate."""

    def __init__(self, inner: LLMProvider, budget: Budget, default_provider: str) -> None:
        self.inner = inner
        self.budget = budget
        self.default_provider = default_provider
        self.name = inner.name
        self.model = inner.model

    def cache_params(self):  # noqa: ANN201
        return self.inner.cache_params()

    async def is_reachable(self) -> bool:
        return await self.inner.is_reachable()

    async def complete(self, messages: list[Message], json_mode: bool = True) -> CompletionResult:
        owner = self.inner.name or self.default_provider
        self.budget.check(owner)
        try:
            result = await self.inner.complete(messages, json_mode)
        except ProviderError as e:
            self.budget.record(owner, e.attempts)
            raise
        self.budget.record(result.provider or owner, 0 if result.cached else result.attempts)
        return result


def estimate_per_question(
    agents: AgentsFile, rounds: int, min_critique_rounds: int, include_c: bool = True
) -> dict[str, tuple[int, int]]:
    """(min, max) HTTP calls per provider for one question that is not cached.

    Debaters: one call per round, rounds 0..R. The minimum assumes the debate stops as soon as
    the app allows; the maximum runs every round. Judge: one call for D, plus one for C unless D
    stopped after round 1 (C then equals D); without C (`include_c=False`) exactly one. Repair
    calls and fallbacks are not included.
    """
    lo_rounds = min(min_critique_rounds, rounds) + 1
    hi_rounds = rounds + 1
    est: dict[str, tuple[int, int]] = {}

    def add(provider: str, lo: int, hi: int) -> None:
        a, b = est.get(provider, (0, 0))
        est[provider] = (a + lo, b + hi)

    for cfg in agents.debaters:
        add(cfg.provider, lo_rounds, hi_rounds)
    add(agents.judge.provider, 1, 2 if include_c else 1)
    return est
