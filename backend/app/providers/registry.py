import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from sqlalchemy.engine import Engine

from app.core.settings import AgentConfig, AgentsFile, ProviderConfig, Settings
from app.providers.base import LLMProvider
from app.providers.cached import CachedProvider
from app.providers.demo_script import DEMO_SCRIPTS
from app.providers.fallback import FallbackProvider, UnavailableProvider
from app.providers.mock import MockProvider, MockScript
from app.providers.openai_compat import OpenAICompatibleProvider
from app.providers.resilience import RateLimiter, RetryPolicy

HEALTH_TIMEOUT_S = 3.0


def build_provider(cfg: AgentConfig, script: MockScript | None = None) -> LLMProvider:
    """Build the deterministic mock provider for one agent (real ones: ProviderRegistry)."""
    if cfg.provider != "mock":
        raise ValueError(f"unknown provider {cfg.provider!r} for agent {cfg.id!r}")
    if script is None:
        factory = DEMO_SCRIPTS.get(cfg.id)
        if factory is None:
            raise ValueError(f"no demo script for mock agent {cfg.id!r}")
        script = factory()
    provider = MockProvider(script)
    provider.name, provider.model = "mock", cfg.model
    return provider


def _model_ids(raw: str) -> set[str]:
    base = raw.removeprefix("models/")  # Gemini lists "models/<id>"
    return {base, base.removesuffix(":latest")}  # Ollama may add ":latest"


class ProviderRegistry:
    """Long-lived providers for every agent: shared semaphores, cache, fallbacks, health.

    Build one per app (not per debate) so per-provider concurrency limits and the health
    cache are shared by every running debate.
    """

    def __init__(
        self,
        agents: AgentsFile,
        settings: Settings,
        engine: Engine | None = None,
        *,
        http_client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rng: random.Random | None = None,
        health_ttl_s: float = 45.0,
        clock: Callable[[], float] = time.monotonic,
        policy: RetryPolicy | None = None,
    ) -> None:
        self.agents = agents
        self.settings = settings
        self.engine = engine
        self._http = http_client
        self._sleep = sleep
        self._rng = rng
        self._policy = (
            policy  # overrides the per-provider default (the smoke script uses 1 attempt)
        )
        self._ttl = health_ttl_s
        self._clock = clock
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._limiters: dict[str, RateLimiter] = {}
        self._by_agent: dict[str, LLMProvider] = {}
        self._owned_health_client: httpx.AsyncClient | None = None
        self._health_cache: dict[tuple[str, str], tuple[float, str]] = {}

    # --- providers ---

    def providers(self) -> dict[str, LLMProvider]:
        return {a.id: self.for_agent(a) for a in self.agents.all_agents()}

    def for_agent(self, cfg: AgentConfig) -> LLMProvider:
        if cfg.id not in self._by_agent:
            self._by_agent[cfg.id] = self._build_for_agent(cfg)
        return self._by_agent[cfg.id]

    def _build_for_agent(self, cfg: AgentConfig) -> LLMProvider:
        if cfg.provider == "mock":
            return build_provider(cfg)
        refs = [(cfg.provider, cfg.model), *((f.provider, f.model) for f in cfg.fallbacks)]
        legs: list[LLMProvider] = []
        primary_skipped = False
        for i, (provider, model) in enumerate(refs):
            leg = self.build_leg(provider, model, cfg)
            if leg is None:
                primary_skipped = primary_skipped or i == 0
            else:
                legs.append(leg)
        if not legs:
            return UnavailableProvider(
                cfg.provider, cfg.model, "no usable provider (missing API keys)"
            )
        if len(legs) == 1 and not primary_skipped:
            return legs[0]
        return FallbackProvider(legs, primary_skipped=primary_skipped)

    def build_leg(self, provider: str, model: str, agent: AgentConfig) -> LLMProvider | None:
        """One (provider, model) leg with `agent`'s generation settings, or None if unconfigured.

        The same construction real debates use; scripts/smoke_providers.py calls it directly.
        """
        pcfg = self.agents.providers[provider]
        options = pcfg.model_options.get(model)
        key = self.settings.api_key(pcfg.api_key_setting)
        if pcfg.api_key_setting and not key:
            return None  # unconfigured: skip, the next leg takes over
        leg: LLMProvider = OpenAICompatibleProvider(
            name=provider,
            model=model,
            base_url=pcfg.base_url,
            api_key=key,
            temperature=agent.temperature,
            max_tokens=agent.max_tokens,
            token_param=pcfg.token_param,
            extra_body=options.extra_body if options else None,
            json_mode=pcfg.json_mode,
            timeout_s=pcfg.timeout_s,
            policy=self._policy or RetryPolicy(max_attempts=pcfg.max_attempts),
            semaphore=self._semaphore(provider, pcfg),
            rate_limiter=self._limiter(provider, pcfg),
            http_client=self._http,
            sleep=self._sleep,
            rng=self._rng,
        )
        if self.engine is not None and self.settings.cache_enabled:
            leg = CachedProvider(leg, self.engine)
        return leg

    def _semaphore(self, provider: str, pcfg: ProviderConfig) -> asyncio.Semaphore:
        return self._semaphores.setdefault(provider, asyncio.Semaphore(pcfg.max_concurrency))

    def _limiter(self, provider: str, pcfg: ProviderConfig) -> RateLimiter | None:
        if pcfg.rpm is None:
            return None
        if provider not in self._limiters:
            self._limiters[provider] = RateLimiter(pcfg.rpm, clock=self._clock, sleep=self._sleep)
        return self._limiters[provider]

    # --- health ---

    async def health(self) -> list[dict[str, Any]]:
        async def one(agent: AgentConfig, role: str) -> dict[str, Any]:
            checks = await asyncio.gather(
                self._check(agent.provider, agent.model),
                *(self._check(f.provider, f.model) for f in agent.fallbacks),
            )
            return {
                "id": agent.id,
                "role": role,
                "persona": agent.persona,
                "provider": agent.provider,
                "model": agent.model,
                "status": checks[0],
                "reachable": checks[0] == "ok",
                "fallbacks": [
                    {"provider": f.provider, "model": f.model, "status": status}
                    for f, status in zip(agent.fallbacks, checks[1:], strict=True)
                ],
            }

        jobs = [one(a, "debater") for a in self.agents.debaters] + [one(self.agents.judge, "judge")]
        return list(await asyncio.gather(*jobs))

    async def _check(self, provider: str, model: str) -> str:
        """ok | no_api_key | unauthorized | model_not_found | rate_limited | unreachable."""
        if provider == "mock":
            return "ok"
        pcfg = self.agents.providers[provider]
        key = self.settings.api_key(pcfg.api_key_setting)
        if pcfg.api_key_setting and not key:
            return "no_api_key"
        cached = self._health_cache.get((provider, model))
        if cached and self._clock() - cached[0] < self._ttl:
            return cached[1]
        status = await self._probe(pcfg, key, model)
        self._health_cache[(provider, model)] = (self._clock(), status)
        return status

    async def _probe(self, pcfg: ProviderConfig, key: str | None, model: str) -> str:
        client = self._http or self._health_client()
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        try:
            resp = await client.get(
                pcfg.base_url.rstrip("/") + "/models", headers=headers, timeout=HEALTH_TIMEOUT_S
            )
        except httpx.HTTPError:
            return "unreachable"
        if resp.status_code in (401, 403):
            return "unauthorized"
        if resp.status_code == 429:
            return "rate_limited"
        if resp.status_code != 200:
            return "unreachable"
        try:
            listed = {i for m in resp.json()["data"] for i in _model_ids(str(m["id"]))}
        except (ValueError, KeyError, TypeError):
            return "ok"  # reachable but the listing is not in the usual shape: cannot disprove
        return "ok" if _model_ids(model) & listed else "model_not_found"

    def _health_client(self) -> httpx.AsyncClient:
        if self._owned_health_client is None:
            self._owned_health_client = httpx.AsyncClient()
        return self._owned_health_client

    async def aclose(self) -> None:
        if self._owned_health_client is not None:
            await self._owned_health_client.aclose()
        for provider in self._by_agent.values():
            for leg in getattr(provider, "chain", [provider]):
                inner = getattr(leg, "inner", leg)
                client = getattr(inner, "_client", None)
                if client is not None and self._http is None:
                    await client.close()
