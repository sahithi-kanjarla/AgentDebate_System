import asyncio
from typing import Any

from fastapi import APIRouter, Request

from app.debate.service import DebateService

router = APIRouter(prefix="/api", tags=["agents"])


@router.get("/agents")
async def list_agents(request: Request) -> list[dict[str, Any]]:
    """Configured agents and provider health.

    Provider and model ids appear only when EXPOSE_AGENT_MODELS is set (local dev); the public
    view omits them, as it does inside debates, until the per-debate reveal.

    `status` is one of ok, no_api_key, unauthorized, model_not_found, rate_limited, unreachable;
    `reachable` is true only for ok. Fallback legs are reported the same way.
    """
    service: DebateService = request.app.state.service
    rows = await _agent_rows(service)
    if service.settings.expose_agent_models:
        return rows
    # Persona -> model is the very thing the reveal protects, and the lineup is the same for every
    # debate, so the public view carries health only.
    return [{k: r[k] for k in _PUBLIC_KEYS if k in r} for r in rows]


_PUBLIC_KEYS = ("id", "role", "persona", "status", "reachable")


async def _agent_rows(service: DebateService) -> list[dict[str, Any]]:
    if service.registry is not None:
        return await service.registry.health()

    # Injected providers (tests, offline demos): ask each one directly.
    providers = service.provider_factory(service.agents)
    cfgs = [(c, "debater") for c in service.agents.debaters] + [(service.agents.judge, "judge")]
    reachable = await asyncio.gather(*(providers[c.id].is_reachable() for c, _ in cfgs))
    return [
        {
            "id": c.id,
            "role": role,
            "persona": c.persona,
            "provider": c.provider,
            "model": c.model,
            "status": "ok" if ok else "unreachable",
            "reachable": ok,
            "fallbacks": [],
        }
        for (c, role), ok in zip(cfgs, reachable, strict=True)
    ]


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
