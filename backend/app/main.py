from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import agents, debates
from app.core.settings import AgentsFile, Settings, get_settings, load_agents
from app.db.session import init_db, make_engine
from app.debate.service import DebateService, ProviderFactory
from app.providers.base import LLMProvider
from app.providers.registry import build_provider


def default_provider_factory(agents: AgentsFile) -> dict[str, LLMProvider]:
    return {c.id: build_provider(c) for c in [*agents.debaters, agents.judge]}


def create_app(
    settings: Settings | None = None, provider_factory: ProviderFactory | None = None
) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = make_engine(settings.database_url)
        init_db(engine)
        service = DebateService(
            engine=engine,
            settings=settings,
            agents=load_agents(settings.agents_config),
            provider_factory=provider_factory or default_provider_factory,
        )
        await service.startup()
        app.state.service = service
        try:
            yield
        finally:
            await service.shutdown()
            engine.dispose()

    app = FastAPI(title="Tribunal", lifespan=lifespan)
    app.include_router(debates.router)
    app.include_router(agents.router)
    return app


app = create_app()
