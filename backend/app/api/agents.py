import asyncio
from typing import Any

from fastapi import APIRouter, Request

from app.debate.service import DebateService

router = APIRouter(prefix="/api", tags=["agents"])


@router.get("/agents")
async def list_agents(request: Request) -> list[dict[str, Any]]:
    """Configured agents and provider health. Model ids are shown here only, never in debates."""
    service: DebateService = request.app.state.service
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
            "reachable": ok,
        }
        for (c, role), ok in zip(cfgs, reachable, strict=True)
    ]


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
