import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api import agents, debates
from app.core.logging import configure_logging
from app.core.ratelimit import AdmissionControl, AdmissionDenied
from app.core.settings import AgentsFile, Settings, get_settings, load_agents
from app.db.session import init_db, make_engine
from app.debate.service import DebateService, ProviderFactory
from app.providers.base import LLMProvider
from app.providers.registry import ProviderRegistry


def create_app(
    settings: Settings | None = None,
    provider_factory: ProviderFactory | None = None,
    *,
    registry_kwargs: dict[str, Any] | None = None,
) -> FastAPI:
    """Build the app. With no `provider_factory`, providers come from a ProviderRegistry
    (real providers, cache, fallbacks). `registry_kwargs` lets tests inject HTTP transports."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(settings.log_level, settings.secret_values())
        app.state.admission = AdmissionControl(settings)
        logging.getLogger("app.admission").info(app.state.admission.describe())
        engine = make_engine(settings.database_url)
        init_db(engine)
        agents_cfg = load_agents(settings.agents_config)
        registry: ProviderRegistry | None = None
        factory = provider_factory
        if factory is None:
            registry = ProviderRegistry(agents_cfg, settings, engine, **(registry_kwargs or {}))

            def factory(_agents: AgentsFile) -> dict[str, LLMProvider]:
                return registry.providers()

        service = DebateService(
            engine=engine,
            settings=settings,
            agents=agents_cfg,
            provider_factory=factory,
            registry=registry,
        )
        await service.startup()
        app.state.service = service
        try:
            yield
        finally:
            await service.shutdown()
            if registry is not None:
                await registry.aclose()
            engine.dispose()

    app = FastAPI(title="Tribunal", lifespan=lifespan)

    @app.exception_handler(AdmissionDenied)
    async def _denied(_request: Request, exc: AdmissionDenied) -> JSONResponse:
        return JSONResponse(
            exc.denial.body(),
            status_code=429,
            headers={"Retry-After": str(exc.denial.retry_after_s)},
        )

    app.include_router(debates.router)
    app.include_router(agents.router)
    return app


app = create_app()
