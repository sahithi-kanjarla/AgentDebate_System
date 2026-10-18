import asyncio
import json
import socket
from collections.abc import AsyncIterator, Callable

import httpx
import pytest

from app.core.settings import BACKEND_DIR, KEY_SETTINGS, AgentsFile, Settings
from app.main import create_app
from app.providers.base import LLMProvider
from app.providers.demo_script import DEMO_SCRIPTS
from app.providers.mock import MockProvider

MOCK_AGENTS = BACKEND_DIR / "config" / "agents.mock.yaml"
REAL_AGENTS = BACKEND_DIR / "config" / "agents.yaml"
_LOOPBACK = {"127.0.0.1", "::1", "localhost", ""}


def _blocked(host) -> None:
    raise RuntimeError(f"network access blocked in tests: {host!r}")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Unit tests must never reach a real provider: only loopback connections are allowed."""
    real_getaddrinfo = socket.getaddrinfo
    real_connect = socket.socket.connect
    real_create_connection = asyncio.BaseEventLoop.create_connection

    def getaddrinfo(host, *args, **kwargs):
        if host not in _LOOPBACK:
            _blocked(host)
        return real_getaddrinfo(host, *args, **kwargs)

    def connect(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if host not in _LOOPBACK:
            _blocked(host)
        return real_connect(self, address)

    async def create_connection(self, protocol_factory, host=None, *args, **kwargs):
        if host not in _LOOPBACK:
            _blocked(host)
        return await real_create_connection(self, protocol_factory, host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(asyncio.BaseEventLoop, "create_connection", create_connection)


@pytest.fixture(autouse=True)
def no_real_keys(monkeypatch):
    """Real keys must not leak into tests through the process environment."""
    for name in KEY_SETTINGS:
        monkeypatch.delenv(name.upper(), raising=False)


def demo_factory(delay_s: float = 0.0) -> Callable[[AgentsFile], dict[str, LLMProvider]]:
    """Provider factory using the demo scripts, optionally slowing every scripted turn."""

    def factory(agents: AgentsFile) -> dict[str, LLMProvider]:
        providers: dict[str, LLMProvider] = {}
        for cfg in [*agents.debaters, agents.judge]:
            script = DEMO_SCRIPTS[cfg.id]()
            for turn in (*script.turns.values(), script.default):
                if turn is not None:
                    turn.delay_s = delay_s
            providers[cfg.id] = MockProvider(script)
        return providers

    return factory


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}", agents_config=MOCK_AGENTS, _env_file=None
    )


@pytest.fixture
async def make_client(settings):
    """Factory: `async with make_client(provider_factory) as (client, app)` with lifespan run."""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _make(provider_factory=None, **overrides) -> AsyncIterator[tuple]:
        app = create_app(settings.model_copy(update=overrides), provider_factory or demo_factory())
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                yield client, app

    return _make


def parse_sse(text: str) -> list[dict]:
    """Parse an SSE body into [{id, event, data}] (data decoded from JSON)."""
    events = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        fields: dict[str, str] = {}
        for line in block.split("\n"):
            if not line or line.startswith(":"):
                continue
            key, _, value = line.partition(":")
            fields[key] = value.removeprefix(" ")
        if "event" in fields:
            events.append(
                {
                    "id": int(fields["id"]),
                    "event": fields["event"],
                    "data": json.loads(fields["data"]),
                }
            )
    return events


async def wait_until(predicate, limit_s: float = 5.0) -> None:
    async with asyncio.timeout(limit_s):
        while not predicate():
            await asyncio.sleep(0.01)
