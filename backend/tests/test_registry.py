import json

import httpx
import pytest
from pydantic import BaseModel

from app.core.settings import AgentConfig, AgentsFile, ProviderConfig, Settings, load_agents
from app.db.session import init_db, make_engine
from app.debate.parsing import parse_with_repair
from app.main import create_app
from app.providers.base import Message, ProviderError
from app.providers.cached import CachedProvider
from app.providers.fallback import FallbackProvider, UnavailableProvider
from app.providers.openai_compat import OpenAICompatibleProvider
from app.providers.registry import ProviderRegistry, _model_ids
from tests.conftest import REAL_AGENTS
from tests.fakes import MSGS, Sleeps, http_client, ok_response

KEYS = {
    "gemini_api_key": "test-key-gemini",
    "groq_api_key": "test-key-groq",
    "openrouter_api_key": "test-key-or",
    "mistral_api_key": "test-key-mistral",
}


class _Ok(BaseModel):
    ok: bool


def settings_for(tmp_path, *, keys=KEYS, **kw) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 't.db'}",
        agents_config=REAL_AGENTS,
        _env_file=None,
        **keys,
        **kw,
    )


def registry(tmp_path, handler, *, keys=KEYS, engine=None, **kw) -> ProviderRegistry:
    return ProviderRegistry(
        load_agents(REAL_AGENTS),
        settings_for(tmp_path, keys=keys),
        engine,
        http_client=http_client(handler),
        sleep=Sleeps(),
        **kw,
    )


def agent(reg: ProviderRegistry, agent_id: str) -> AgentConfig:
    return next(a for a in reg.agents.all_agents() if a.id == agent_id)


def chat_ok(request):
    return ok_response('{"ok": true}')


# --- provider construction ---


def test_real_config_builds_fallback_chains_with_shared_semaphores(tmp_path):
    reg = registry(tmp_path, chat_ok)
    providers = reg.providers()
    d2, judge = providers["debater_2"], providers["judge"]
    assert isinstance(d2, FallbackProvider) and [leg.name for leg in d2.chain] == ["groq", "ollama"]
    assert [leg.name for leg in providers["debater_3"].chain] == ["openrouter", "mistral", "ollama"]
    assert [leg.name for leg in judge.chain] == ["groq", "mistral", "gemini", "ollama"]
    # debater_2 and the judge use different Groq models but share one concurrency limit.
    assert d2.chain[0].model != judge.chain[0].model
    assert d2.chain[0]._semaphore is judge.chain[0]._semaphore
    assert set(reg._semaphores) == {"gemini", "groq", "openrouter", "mistral", "ollama"}
    assert reg.for_agent(agent(reg, "debater_2")) is d2  # built once, reused by every debate


async def test_missing_key_skips_the_primary_and_marks_the_fallback(tmp_path):
    hosts = []

    def handler(request):
        hosts.append(request.url.host)
        return ok_response()

    keys = {k: v for k, v in KEYS.items() if k != "gemini_api_key"}
    reg = registry(tmp_path, handler, keys=keys)
    d1 = reg.for_agent(agent(reg, "debater_1"))
    result = await d1.complete(MSGS)
    assert hosts == ["localhost"]  # Gemini was never contacted
    assert (result.provider, result.model) == ("ollama", "gemma4:e4b") and result.fallback_used


async def test_no_keys_at_all_still_answers_through_ollama(tmp_path):
    reg = registry(tmp_path, chat_ok, keys={})
    for a in reg.agents.all_agents():
        result = await reg.for_agent(a).complete(MSGS)
        assert result.provider == "ollama" and result.fallback_used


async def test_agent_with_no_usable_provider_fails_cleanly(tmp_path):
    agents = AgentsFile(
        providers={"groq": ProviderConfig(base_url="https://x/v1", api_key_setting="groq_api_key")},
        debaters=[AgentConfig(id="d", persona="P", provider="groq", model="m")],
        judge=AgentConfig(id="j", persona="J", provider="groq", model="m"),
    )
    reg = ProviderRegistry(
        agents, settings_for(tmp_path, keys={}), http_client=http_client(chat_ok)
    )
    p = reg.for_agent(agents.debaters[0])
    assert isinstance(p, UnavailableProvider)
    with pytest.raises(ProviderError, match="no usable provider"):
        await p.complete(MSGS)


def test_cache_wrapping_follows_settings_and_engine(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'c.db'}")
    init_db(engine)
    cached = registry(tmp_path, chat_ok, engine=engine).for_agent(
        agent_in := load_agents(REAL_AGENTS).debaters[0]
    )
    assert isinstance(cached.chain[0], CachedProvider)
    assert isinstance(cached.chain[0].inner, OpenAICompatibleProvider)

    no_engine = registry(tmp_path, chat_ok).for_agent(agent_in)
    assert isinstance(no_engine.chain[0], OpenAICompatibleProvider)

    off = ProviderRegistry(
        load_agents(REAL_AGENTS),
        settings_for(tmp_path, cache_enabled=False),
        engine,
        http_client=http_client(chat_ok),
    ).for_agent(agent_in)
    assert isinstance(off.chain[0], OpenAICompatibleProvider)
    engine.dispose()


def test_per_agent_generation_settings_come_from_yaml(tmp_path):
    reg = registry(tmp_path, chat_ok)
    judge_leg = reg.for_agent(agent(reg, "judge")).chain[0]
    assert judge_leg.temperature == 0.2 and judge_leg.max_tokens == 1536


# --- health ---


def models_handler(overrides: dict[str, httpx.Response | Exception] | None = None):
    listings = {
        "generativelanguage.googleapis.com": ["models/gemini-3.5-flash-lite"],
        "api.groq.com": ["openai/gpt-oss-120b", "openai/gpt-oss-20b"],
        "openrouter.ai": ["nvidia/nemotron-3-super-120b-a12b:free"],
        "api.mistral.ai": ["mistral-medium-3.5"],
        "localhost": ["gemma4:e4b"],
    }
    calls: list[str] = []

    def handler(request):
        host = request.url.host
        calls.append(host)
        assert request.url.path.endswith("/models")
        override = (overrides or {}).get(host)
        if isinstance(override, Exception):
            raise override
        if override is not None:
            return override
        return httpx.Response(200, json={"data": [{"id": i} for i in listings[host]]})

    handler.calls = calls
    return handler


async def test_health_reports_ok_when_everything_is_listed(tmp_path):
    handler = models_handler()
    health = await registry(tmp_path, handler).health()
    assert {h["id"]: h["status"] for h in health} == {
        "debater_1": "ok",
        "debater_2": "ok",
        "debater_3": "ok",
        "judge": "ok",
    }
    assert all(h["reachable"] for h in health)
    d3 = next(h for h in health if h["id"] == "debater_3")
    assert [(f["provider"], f["status"]) for f in d3["fallbacks"]] == [
        ("mistral", "ok"),
        ("ollama", "ok"),
    ]


async def test_health_distinguishes_failure_modes(tmp_path):
    handler = models_handler(
        {
            "api.groq.com": httpx.Response(401),
            "openrouter.ai": httpx.Response(200, json={"data": [{"id": "some/other-model"}]}),
            "localhost": httpx.ConnectError("refused"),
        }
    )
    health = {h["id"]: h for h in await registry(tmp_path, handler).health()}
    assert health["debater_1"]["status"] == "ok"
    assert health["debater_1"]["fallbacks"][0]["status"] == "unreachable"  # Ollama down
    assert health["debater_2"]["status"] == "unauthorized" and not health["debater_2"]["reachable"]
    assert health["debater_3"]["status"] == "model_not_found"
    assert health["judge"]["status"] == "unauthorized"  # Groq
    assert health["judge"]["fallbacks"][0]["status"] == "ok"  # Mistral
    assert health["judge"]["fallbacks"][1] == {
        "provider": "gemini",
        "model": "gemini-3.5-flash-lite",
        "status": "ok",
    }


@pytest.mark.parametrize(
    "response,expected",
    [
        (httpx.Response(429), "rate_limited"),
        (httpx.Response(503), "unreachable"),
        (httpx.Response(200, text="not json"), "ok"),
        (httpx.Response(200, json={"unexpected": 1}), "ok"),
        (httpx.ReadTimeout("slow"), "unreachable"),
    ],
)
async def test_health_status_mapping(tmp_path, response, expected):
    handler = models_handler({"api.groq.com": response})
    health = {h["id"]: h for h in await registry(tmp_path, handler).health()}
    assert health["debater_2"]["status"] == expected


async def test_health_reports_missing_keys_without_any_http_call(tmp_path):
    handler = models_handler()
    reg = registry(tmp_path, handler, keys={})
    health = {h["id"]: h for h in await reg.health()}
    assert health["debater_1"]["status"] == "no_api_key" and not health["debater_1"]["reachable"]
    assert set(handler.calls) == {"localhost"}  # only keyless Ollama was probed


async def test_health_results_are_cached_for_the_ttl(tmp_path):
    handler = models_handler()
    now = [1000.0]
    reg = registry(tmp_path, handler, health_ttl_s=45, clock=lambda: now[0])
    await reg.health()
    first = len(handler.calls)
    await reg.health()
    assert len(handler.calls) == first  # served from cache
    now[0] += 46
    await reg.health()
    assert len(handler.calls) == 2 * first


async def test_health_output_never_contains_keys(tmp_path):
    health = await registry(tmp_path, models_handler()).health()
    blob = json.dumps(health)
    assert not any(key in blob for key in KEYS.values())


def test_model_id_normalization():
    assert "gemini-3.5-flash-lite" in _model_ids("models/gemini-3.5-flash-lite")
    assert _model_ids("gemma4:e4b:latest") & _model_ids("gemma4:e4b")


async def test_agents_endpoint_uses_real_health(tmp_path):
    app = create_app(
        settings_for(tmp_path, expose_agent_models=True),
        registry_kwargs={"http_client": http_client(models_handler())},
    )
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/agents")
    agents = resp.json()
    assert [a["id"] for a in agents] == ["debater_1", "debater_2", "debater_3", "judge"]
    assert agents[1]["model"] == "openai/gpt-oss-120b" and agents[1]["status"] == "ok"
    assert agents[2]["fallbacks"][0]["provider"] == "mistral"
    assert not any(key in resp.text for key in KEYS.values())


async def test_mock_config_runs_through_the_registry_path(tmp_path):
    """AGENTS_CONFIG=config/agents.mock.yaml: the offline demo, no keys, no HTTP at all."""
    from tests.conftest import MOCK_AGENTS, parse_sse, wait_until

    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'm.db'}", agents_config=MOCK_AGENTS, _env_file=None
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            agents = (await client.get("/api/agents")).json()
            assert all(a["status"] == "ok" and a["reachable"] for a in agents)
            debate_id = (await client.post("/api/debates", json={"question": "q"})).json()["id"]
            events = parse_sse((await client.get(f"/api/debates/{debate_id}/stream")).text)
            await wait_until(lambda: not app.state.service._channels)
    assert events[-1]["event"] == "done" and events[-1]["data"]["stats"]["calls"] == 7


def test_groq_legs_get_token_param_and_reasoning_options_from_yaml(tmp_path):
    reg = registry(tmp_path, chat_ok)
    d2_groq = reg.for_agent(agent(reg, "debater_2")).chain[0]
    judge_groq = reg.for_agent(agent(reg, "judge")).chain[0]
    for leg in (d2_groq, judge_groq):
        assert leg.token_param == "max_completion_tokens"
        assert leg.extra_body == {"reasoning_effort": "low"}
    gemini = reg.for_agent(agent(reg, "debater_1")).chain[0]
    assert gemini.token_param == "max_tokens" and gemini.extra_body == {}


def _pairs(a):
    return [(a.provider, a.model), *((f.provider, f.model) for f in a.fallbacks)]


def test_no_retired_groq_models_in_the_real_config():
    cfg = load_agents(REAL_AGENTS)
    used = {m for a in cfg.all_agents() for _, m in _pairs(a)}
    assert "llama-3.3-70b-versatile" not in used and "llama-3.1-8b-instant" not in used
    # every Groq model in use has its reasoning options configured
    groq_models = {m for a in cfg.all_agents() for p, m in _pairs(a) if p == "groq"}
    assert groq_models <= set(cfg.providers["groq"].model_options)


def test_registry_build_leg_applies_a_policy_override(tmp_path):
    from app.providers.resilience import RetryPolicy

    reg = ProviderRegistry(
        load_agents(REAL_AGENTS),
        settings_for(tmp_path),
        http_client=http_client(chat_ok),
        policy=RetryPolicy(max_attempts=1),
    )
    leg = reg.build_leg("groq", "openai/gpt-oss-120b", agent(reg, "debater_2"))
    assert leg._policy.max_attempts == 1
    assert reg.build_leg("gemini", "x", agent(reg, "debater_1")) is not None
    no_key = ProviderRegistry(load_agents(REAL_AGENTS), settings_for(tmp_path, keys={}))
    assert no_key.build_leg("gemini", "x", agent(no_key, "debater_1")) is None


# --- Mistral and rpm ---


def test_mistral_is_pinned_and_rate_limited_in_the_real_config(tmp_path):
    cfg = load_agents(REAL_AGENTS)
    mistral = cfg.providers["mistral"]
    assert mistral.base_url == "https://api.mistral.ai/v1" and mistral.rpm == 2
    models = {m for a in cfg.all_agents() for p, m in _pairs(a) if p == "mistral"}
    assert models and not any("latest" in m for m in models)
    assert [a.provider for a in cfg.debaters] == ["gemini", "groq", "openrouter"]
    assert cfg.judge.provider == "groq"
    assert [f.provider for f in cfg.judge.fallbacks] == ["mistral", "gemini", "ollama"]
    reg = registry(tmp_path, chat_ok)
    d3 = reg.for_agent(agent(reg, "debater_3"))
    judge = reg.for_agent(agent(reg, "judge"))
    assert d3.chain[1]._rate_limiter is judge.chain[1]._rate_limiter is not None
    assert reg.for_agent(agent(reg, "debater_1")).chain[0]._rate_limiter is None


async def test_mistral_json_mode_is_sent_to_the_mistral_endpoint(tmp_path):
    seen = []

    def handler(request):
        seen.append(
            (request.url.host, request.headers["authorization"], json.loads(request.content))
        )
        return ok_response()

    reg = registry(tmp_path, handler)
    leg = reg.build_leg("mistral", "mistral-medium-3.5", agent(reg, "debater_3"))
    await leg.complete(MSGS)
    host, auth, body = seen[0]
    assert host == "api.mistral.ai" and auth == "Bearer test-key-mistral"
    assert body["response_format"] == {"type": "json_object"}
    assert body["model"] == "mistral-medium-3.5" and "max_tokens" in body


async def test_provider_json_mode_none_sends_no_response_format_but_default_does(tmp_path):
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return ok_response('Sure! Here it is:\n```json\n{"ok": true}\n```')

    reg = registry(tmp_path, handler)
    d1 = agent(reg, "debater_1")
    reg.agents.providers["gemini"].json_mode = "none"
    off = reg.build_leg("gemini", d1.model, d1)
    reg.agents.providers["gemini"].json_mode = "json_object"
    on = reg.build_leg("gemini", d1.model, d1)
    system = [Message(role="system", content="JSON only."), Message(role="user", content="go")]
    outcome = await parse_with_repair(off, system, _Ok)  # plain-text reply, still parsed
    await on.complete(system)
    assert outcome.valid and outcome.calls == 1
    assert "response_format" not in bodies[0] and bodies[0]["messages"][0]["role"] == "system"
    assert bodies[1]["response_format"] == {"type": "json_object"}


async def test_rpm_spaces_calls_instead_of_hitting_429(tmp_path):
    now = [100.0]
    sleeps = Sleeps()

    async def sleep(delay):
        await sleeps(delay)
        now[0] += delay  # sleeping moves the fake clock

    reg = ProviderRegistry(
        load_agents(REAL_AGENTS),
        settings_for(tmp_path),
        http_client=http_client(chat_ok),
        sleep=sleep,
        clock=lambda: now[0],
    )
    leg = reg.build_leg("mistral", "mistral-medium-3.5", agent(reg, "debater_3"))
    for _ in range(3):
        await leg.complete(MSGS)
    assert sleeps.delays == [30.0, 30.0]  # rpm 2 => first call free, then one per 30s
    now[0] += 120  # idle for a while: the next call is immediate again
    await leg.complete(MSGS)
    assert sleeps.delays == [30.0, 30.0]
