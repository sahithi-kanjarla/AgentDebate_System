"""The container has no Ollama. Its fallback legs must fail fast, the chain must move on, and the
public agent list must not show them."""

import socket
import time

import httpx
import pytest

from app.core.settings import Settings
from app.main import create_app
from app.providers.base import ProviderError
from app.providers.fallback import FallbackProvider
from app.providers.openai_compat import OpenAICompatibleProvider
from tests.conftest import REAL_AGENTS
from tests.fakes import MSGS, ok_response
from tests.test_registry import KEYS, models_handler

# Linux refuses a closed loopback port at once, so the real worst case is the retry backoff, 3 s.
# Windows takes about 2 s per refused connect (about 8 s for three attempts), so the bound is set
# at 20 s: far from a 180 s timeout, which is the failure this guards against.
FAST = 20.0


def closed_loopback_port() -> int:
    """A port on 127.0.0.1 with nothing listening: connecting is refused immediately."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def ollama_leg() -> OpenAICompatibleProvider:
    # The real Ollama settings from agents.yaml: a 180 s timeout and the default retry policy.
    return OpenAICompatibleProvider(
        name="ollama",
        model="gemma4:e4b",
        base_url=f"http://127.0.0.1:{closed_loopback_port()}/v1/",
        api_key=None,
        timeout_s=180.0,
    )


async def test_refused_ollama_connection_fails_fast_without_waiting_for_the_timeout():
    started = time.monotonic()
    with pytest.raises(ProviderError) as err:
        await ollama_leg().complete(MSGS)  # real socket, real sleeps, real retry policy
    elapsed = time.monotonic() - started
    assert err.value.category == "unreachable"
    assert err.value.attempts == 3  # the default policy: three tries, backoff at most 1 s + 2 s
    assert elapsed < FAST, f"took {elapsed:.1f}s"


async def test_the_chain_moves_on_past_a_refused_ollama_leg():
    backup = OpenAICompatibleProvider(
        name="gemini",
        model="m",
        base_url="http://127.0.0.1:9/v1/",  # never reached: the mock transport answers
        api_key="k",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: ok_response("fine"))),
    )
    chain = FallbackProvider([ollama_leg(), backup])
    started = time.monotonic()
    result = await chain.complete(MSGS)
    assert result.text == "fine" and result.provider == "gemini" and result.fallback_used
    assert time.monotonic() - started < FAST


async def test_a_chain_that_ends_in_a_refused_ollama_fails_cleanly_not_slowly():
    chain = FallbackProvider([ollama_leg()])
    started = time.monotonic()
    with pytest.raises(ProviderError) as err:
        await chain.complete(MSGS)
    assert err.value.category == "all_providers_failed"
    assert time.monotonic() - started < FAST


async def test_public_agent_list_hides_fallback_legs_even_when_ollama_is_refused(tmp_path):
    handler = models_handler({"localhost": httpx.ConnectError("refused")})
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'a.db'}",
        agents_config=REAL_AGENTS,
        expose_agent_models=False,
        _env_file=None,
        **KEYS,
    )
    app = create_app(
        settings,
        registry_kwargs={"http_client": httpx.AsyncClient(transport=httpx.MockTransport(handler))},
    )
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            r = await client.get("/api/agents")
    rows = r.json()
    assert r.status_code == 200 and len(rows) == 4
    assert all(set(row) == {"id", "role", "persona", "status", "reachable"} for row in rows)
    # The primary models answer; the refused Ollama leg changes nothing the visitor can see.
    assert all(row["status"] == "ok" and row["reachable"] for row in rows)
    text = r.text.lower()
    for term in ("ollama", "gemma", "fallback", "localhost", "11434", "groq", "gemini", "mistral"):
        assert term not in text
