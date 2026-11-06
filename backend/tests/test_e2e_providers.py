"""Whole debates through the HTTP app, real agents.yaml, fake providers over a mock transport.

"Killing" a provider means its host answers 503/401. No test here touches the network.
"""

import asyncio
import json
import random

import httpx
import pytest

from app.core.settings import Settings
from app.db import repo
from app.main import create_app
from app.providers.base import Message
from app.providers.demo_script import DEMO_SCRIPTS
from app.providers.mock import MockProvider
from tests.conftest import REAL_AGENTS, parse_sse, wait_until
from tests.fakes import Sleeps, error_response, http_client, ok_response

GEMINI, GROQ, OPENROUTER, MISTRAL, OLLAMA = (
    "generativelanguage.googleapis.com",
    "api.groq.com",
    "openrouter.ai",
    "api.mistral.ai",
    "localhost",
)
KEYS = {
    "gemini_api_key": "test-key-gemini",
    "groq_api_key": "test-key-groq",
    "openrouter_api_key": "test-key-or",
    "mistral_api_key": "test-key-mistral",
}
PERSONAS = {"Solver": "debater_1", "Skeptic": "debater_2", "Fact-Checker": "debater_3"}


class FakeProviders:
    """One fake server for all five hosts. Replies come from the M1 demo scripts, chosen by the
    persona named in the system prompt, so any provider can answer for any agent."""

    def __init__(self, down=(), unauthorized=()) -> None:
        self.down, self.unauthorized = set(down), set(unauthorized)
        self.requests: list[tuple[str, str]] = []  # (host, model)
        self.bodies: list[tuple[str, dict]] = []  # (host, request body)

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        host = request.url.host
        self.requests.append((host, body["model"]))
        self.bodies.append((host, body))
        if host in self.down:
            return error_response(503)
        if host in self.unauthorized:
            return error_response(401)
        messages = [Message(**m) for m in body["messages"]]
        joined = "\n".join(m.content for m in messages)
        if "ROLE: judge" in joined:
            agent_id = "judge"
        else:
            agent_id = next(
                i for p, i in PERSONAS.items() if f"You are {p}," in messages[0].content
            )
        reply = await MockProvider(DEMO_SCRIPTS[agent_id]()).complete(messages)
        return ok_response(reply.text, model=body["model"])

    def count(self, host: str) -> int:
        return sum(1 for h, _ in self.requests if h == host)


class World:
    def __init__(self, tmp_path, fake: FakeProviders, keys=KEYS) -> None:
        self.fake = fake
        self.public_raw: list[str] = []  # what the browser could read, per debate
        self.sleeps = Sleeps()
        self.settings = Settings(
            database_url=f"sqlite:///{tmp_path / 'e2e.db'}",
            agents_config=REAL_AGENTS,
            _env_file=None,
            **keys,
        )
        self.app = create_app(
            self.settings,
            registry_kwargs={
                "http_client": http_client(fake),
                "sleep": self.sleeps,
                "rng": random.Random(0),
            },
        )

    async def run_debate(self, client: httpx.AsyncClient, question="What is 17 * 24?"):
        resp = await client.post("/api/debates", json={"question": question})
        debate_id = resp.json()["id"]
        stream = await client.get(f"/api/debates/{debate_id}/stream")
        await wait_until(lambda: not self.app.state.service._channels)
        got = await client.get(f"/api/debates/{debate_id}")
        replay = await client.get(f"/api/debates/{debate_id}/stream")
        self.public_raw += [got.text, replay.text]
        stored = got.json()
        # The API withholds provider and model; these tests check who really answered, so they
        # read the stored turns from the database (the reveal endpoint is tested separately).
        full = await asyncio.to_thread(repo.get_debate, self.app.state.service.engine, debate_id)
        stored["turns"] = full["turns"]
        return parse_sse(stream.text), stored, stream.text


@pytest.fixture
async def run_world(tmp_path):
    async def run(fake: FakeProviders, *, keys=KEYS, debates=1):
        world = World(tmp_path, fake, keys)
        results = []
        async with world.app.router.lifespan_context(world.app):
            transport = httpx.ASGITransport(app=world.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                for _ in range(debates):
                    results.append(await world.run_debate(client))
        return world, results

    return run


def by_agent(events, round_):
    return {
        e["data"]["agent"]: e["data"]["payload"]
        for e in events
        if e["event"] == "agent_response" and e["data"]["round"] == round_
    }


def turns_of(stored, agent_id):
    return [t for t in stored["turns"] if t["agent_id"] == agent_id]


async def test_all_providers_healthy(run_world):
    fake = FakeProviders()
    world, [(events, stored, _)] = await run_world(fake)
    assert [e["event"] for e in events][-2:] == ["judge_verdict", "done"]
    assert stored["status"] == "completed" and stored["verdict"]["final_answer"] == "408"
    # Mistral answers debater_3 twice; rpm 20 spaces those calls 3s apart: the only sleep.
    assert len(world.sleeps.delays) == 1 and world.sleeps.delays[0] <= 3.0
    primaries = {t["agent_id"]: (t["provider"], t["fallback_used"]) for t in stored["turns"]}
    assert primaries == {
        "debater_1": ("gemini", False),
        "debater_2": ("groq", False),
        "debater_3": ("mistral", False),
        "judge": ("groq", False),
    }
    assert events[-1]["data"]["stats"]["fallbacks"] == 0


async def test_killing_groq_triggers_fallback_and_the_debate_still_completes(run_world):
    fake = FakeProviders(down=[GROQ])
    world, [(events, stored, raw)] = await run_world(fake)

    # The debate finished normally with the correct verdict.
    assert stored["status"] == "completed" and [e["event"] for e in events][-1] == "done"
    assert stored["verdict"]["final_answer"] == "408"
    assert [e["data"]["round"] for e in events if e["event"] == "round_complete"] == [0, 1]
    assert not [e for e in events if e["event"] == "error"]  # fallback is not an error

    # Groq was retried (3 attempts per call) before giving up: 2 debater_2 rounds + the judge.
    # Plus 2 rpm waits (3s each) spacing Mistral's three calls: debater_3 twice, then the judge.
    assert fake.count(GROQ) == 9 and len(world.sleeps.delays) == 6 + 2
    assert fake.count(OLLAMA) == 2  # debater_2's two turns, answered locally

    # The transcript records who really answered.
    d2 = turns_of(stored, "debater_2")
    assert [(t["provider"], t["model"], t["fallback_used"]) for t in d2] == [
        ("ollama", "gemma4:e4b", True)
    ] * 2
    assert all(t["valid"] for t in d2)
    judge = turns_of(stored, "judge")[0]
    assert (judge["provider"], judge["fallback_used"]) == ("mistral", True)  # first judge fallback
    for agent_id in ("debater_1", "debater_3"):
        assert all(not t["fallback_used"] for t in turns_of(stored, agent_id))

    # The live stream flags the fallback but stays anonymous.
    for round_ in (0, 1):
        payloads = by_agent(events, round_)
        assert payloads["Debater 2"]["fallback_used"] is True
        assert payloads["Debater 1"]["fallback_used"] is False
        assert payloads["Debater 3"]["fallback_used"] is False
    lowered = raw.lower()
    hidden = (
        "groq",
        "gemini",
        "openrouter",
        "ollama",
        "gpt-oss",
        "llama",
        "mistral",
        "ministral",
        "gemma",
    )
    for name in hidden:
        assert name not in lowered

    # Quota accounting counts the failed attempts too: 7 completions + 9 failed groq requests.
    stats = events[-1]["data"]["stats"]
    assert stats["calls"] == 7 and stats["api_calls"] == 16 and stats["fallbacks"] == 3


async def test_unauthorized_provider_falls_back_without_retrying(run_world):
    fake = FakeProviders(unauthorized=[MISTRAL])
    world, [(events, stored, _)] = await run_world(fake)
    assert stored["status"] == "completed"
    assert fake.count(MISTRAL) == 2  # one try per call, no retries
    d3 = turns_of(stored, "debater_3")
    assert [(t["provider"], t["model"], t["fallback_used"]) for t in d3] == [
        ("ollama", "gemma4:e4b", True)
    ] * 2
    assert fake.count(OLLAMA) == 2
    # The only sleep is the rpm 20 spacing (3s) between the two Mistral calls, not a retry backoff.
    assert len(world.sleeps.delays) <= 1 and all(d <= 3.0 for d in world.sleeps.delays)


async def test_missing_gemini_key_means_gemini_is_never_contacted(run_world):
    keys = {k: v for k, v in KEYS.items() if k != "gemini_api_key"}
    fake = FakeProviders()
    _, [(events, stored, _)] = await run_world(fake, keys=keys)
    assert stored["status"] == "completed"
    assert fake.count(GEMINI) == 0
    d1 = turns_of(stored, "debater_1")
    assert all((t["provider"], t["fallback_used"]) == ("ollama", True) for t in d1)


async def test_with_no_keys_the_whole_debate_runs_on_local_ollama(run_world):
    fake = FakeProviders()
    _, [(events, stored, _)] = await run_world(fake, keys={})
    assert stored["status"] == "completed" and stored["verdict"]["final_answer"] == "408"
    assert {h for h, _ in fake.requests} == {OLLAMA}


async def test_second_identical_debate_is_served_from_the_cache(run_world):
    fake = FakeProviders()
    _, [(first, _, _), (second, _, _)] = await run_world(fake, debates=2)
    after_first = len(fake.requests)
    assert after_first == 7
    stats = second[-1]["data"]["stats"]
    assert stats["cache_hits"] == 7 and stats["api_calls"] == 0
    assert first[-2]["data"]["payload"] == second[-2]["data"]["payload"]  # same verdict


async def test_failures_are_not_cached(run_world):
    # Groq is down for the first debate; a fallback answer is cached under *ollama's* key only.
    fake = FakeProviders(down=[GROQ])
    _, [(_, _, _), (second, _, _)] = await run_world(fake, debates=2)
    # Second debate: ollama/gemini answers are cached, but groq must be tried again (not cached).
    assert fake.count(GROQ) == 18
    assert second[-1]["data"]["stats"]["cache_hits"] == 7


async def test_every_provider_down_degrades_gracefully(run_world):
    fake = FakeProviders(down=[GEMINI, GROQ, OPENROUTER, MISTRAL, OLLAMA])
    _, [(events, stored, _)] = await run_world(fake)
    kinds = [e["event"] for e in events]
    assert kinds[0] == "debate_started" and kinds[-2:] == ["judge_verdict", "done"]
    assert stored["status"] == "completed"
    errors = [e["data"] for e in events if e["event"] == "error"]
    assert errors and all(e["recoverable"] for e in errors)
    assert all("all providers failed" in e["message"] for e in errors)
    assert not any(t["valid"] for t in stored["turns"])
    assert stored["verdict"]["final_answer"] == "No valid answer"
    assert not any(key in json.dumps(events) for key in KEYS.values())


async def test_groq_requests_use_the_current_token_param_and_low_reasoning(run_world):
    fake = FakeProviders()
    await run_world(fake)
    groq = [b for host, b in fake.bodies if host == GROQ]
    assert groq and all(b["model"].startswith("openai/gpt-oss") for b in groq)
    for body in groq:
        assert body["max_completion_tokens"] == 2048 and "max_tokens" not in body
        assert body["reasoning_effort"] == "low"
    # providers without special options still use plain max_tokens and no extras
    other = [b for host, b in fake.bodies if host != GROQ]
    assert all("max_tokens" in b and "reasoning_effort" not in b for b in other)


async def test_serve_paths_hide_the_real_lineup_even_after_fallbacks(run_world):
    from tests.test_reveal import assert_anonymous, config_terms

    fake = FakeProviders(down=[GROQ])
    world, _ = await run_world(fake)
    terms = config_terms(REAL_AGENTS)
    assert {"groq", "ollama", "openai/gpt-oss-20b"} <= terms
    assert len(world.public_raw) == 2
    for raw in world.public_raw:
        assert_anonymous(raw, terms)
