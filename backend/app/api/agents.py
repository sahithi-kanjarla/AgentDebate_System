import asyncio
from typing import Any

from fastapi import APIRouter, Request

from app.debate.service import DebateService

router = APIRouter(prefix="/api", tags=["agents"])


@router.get("/agents")
async def list_agents(request: Request) -> list[dict[str, Any]]:
    """Configured agents and provider health. Model ids are shown here only, never in debates.

    `status` is one of ok, no_api_key, unauthorized, model_not_found, rate_limited, unreachable;
    `reachable` is true only for ok. Fallback legs are reported the same way.
    """
    service: DebateService = request.app.state.service
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
