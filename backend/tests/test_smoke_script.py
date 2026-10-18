"""The manual smoke script, driven against a fake transport (it never touches the network)."""

import importlib.util
from pathlib import Path

import httpx

from app.core.settings import Settings, load_agents
from app.providers.base import ProviderError
from app.providers.registry import ProviderRegistry
from app.providers.resilience import RetryPolicy
from tests.conftest import REAL_AGENTS
from tests.fakes import FAKE_KEY, body_of, http_client, ok_response

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "smoke_providers.py"
spec = importlib.util.spec_from_file_location("smoke_providers", SCRIPT)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)

KEYS = {"gemini_api_key": FAKE_KEY, "groq_api_key": FAKE_KEY, "openrouter_api_key": FAKE_KEY}
GPT_OSS_120B = "openai/gpt-oss-120b"


def setup(handler, keys=KEYS):
    settings = Settings(agents_config=REAL_AGENTS, _env_file=None, **keys)
    agents = load_agents(REAL_AGENTS)
    http = http_client(handler)
    registry = ProviderRegistry(
        agents, settings, None, http_client=http, policy=RetryPolicy(max_attempts=1)
    )
    return settings, agents, registry, http


def pair(agents, provider, model):
    return next(
        (p, m, a) for p, m, a in smoke.pairs_to_check(agents, []) if (p, m) == (provider, model)
    )


async def run_check(handler, provider, model, *, verbose=False, keys=KEYS):
    settings, agents, registry, http = setup(handler, keys)
    _, _, agent = pair(agents, provider, model)
    return await smoke.check(
        settings, agents, registry, provider, model, agent, verbose=verbose, http=http
    )


def groq_server(*, fail_json_mode=False, status=None, message="bad", ids=None):
    """A fake Groq: /models listing plus chat completions; optional scripted failures."""
    ids = ids or [GPT_OSS_120B, "openai/gpt-oss-20b"]
    seen = []

    def handler(request):
        if request.url.path.endswith("/models"):
            data = [{"id": i, "owned_by": "SECRET-ORG"} for i in ids]
            return httpx.Response(200, json={"data": data})
        body = body_of(request)
        seen.append(body)
        if status:
            err = {"message": message, "type": "invalid_request_error", "code": "x"}
            return httpx.Response(status, json={"error": err})
        if fail_json_mode and "response_format" in body:
            err = {
                "message": "Failed to generate JSON. Please adjust your prompt.",
                "type": "invalid_request_error",
                "code": "json_validate_failed",
            }
            return httpx.Response(400, json={"error": err})
        return ok_response('{"ok": true}')

    handler.seen = seen
    return handler


async def test_pass_line_has_latency_and_no_secrets(capsys):
    assert await run_check(groq_server(), "groq", GPT_OSS_120B)
    out = capsys.readouterr().out
    assert out.startswith("PASS  groq") and " ms" in out and FAKE_KEY not in out


async def test_smoke_builds_the_leg_like_a_real_debate():
    handler = groq_server()
    assert await run_check(handler, "groq", GPT_OSS_120B)
    body = handler.seen[0]
    assert body["max_completion_tokens"] == 1536 and "max_tokens" not in body  # token_param
    assert body["reasoning_effort"] == "low"  # per-model options
    assert body["temperature"] == 0.6  # the agent's own setting
    assert body["response_format"] == {"type": "json_object"}


async def test_smoke_exercises_the_same_json_mode_fallback_as_real_debates(capsys):
    handler = groq_server(fail_json_mode=True)
    assert await run_check(handler, "groq", GPT_OSS_120B)  # PASS despite the 400
    assert len(handler.seen) == 2 and "response_format" not in handler.seen[1]
    assert "2 requests" in capsys.readouterr().out


async def test_failure_prints_only_a_category_by_default(capsys):
    handler = groq_server(status=400, message=f"nope {FAKE_KEY} SECRET-DETAIL")
    assert not await run_check(handler, "groq", GPT_OSS_120B)
    out = capsys.readouterr().out
    assert out.startswith("FAIL  groq") and "bad_request (HTTP 400)" in out
    assert "SECRET-DETAIL" not in out and FAKE_KEY not in out and "message=" not in out


async def test_verbose_errors_show_message_and_type_scrubbed_and_truncated(capsys):
    handler = groq_server(status=400, message=f"bad {FAKE_KEY} " + "x" * 500)
    assert not await run_check(handler, "groq", GPT_OSS_120B, verbose=True)
    out = capsys.readouterr().out
    detail = next(line for line in out.splitlines() if "message=" in line)
    assert "type=invalid_request_error" in detail
    assert FAKE_KEY not in out and "[REDACTED]" in detail
    assert "x" * 201 not in detail
    for forbidden in ("authorization", "bearer", "headers", "{"):
        assert forbidden not in out.lower()


def test_describe_error_truncates_and_scrubs():
    e = ProviderError(
        "bad_request (HTTP 400)",
        status=400,
        detail="a" * 300 + FAKE_KEY,
        error_type="invalid_request_error",
    )
    text = smoke.describe_error(e, [FAKE_KEY])
    assert "a" * 200 in text and "a" * 201 not in text and FAKE_KEY not in text
    assert text.endswith("type=invalid_request_error")
    blank = smoke.describe_error(ProviderError("x"), [FAKE_KEY])
    assert "(no message)" in blank and "type=-" in blank


async def test_model_missing_from_the_listing_fails_without_a_completion(capsys):
    handler = groq_server(ids=["some-other-model"])
    assert not await run_check(handler, "groq", GPT_OSS_120B)
    assert handler.seen == [] and "model_not_found" in capsys.readouterr().out


async def test_missing_key_is_skipped_without_any_request(capsys):
    handler = groq_server()
    keys = {k: v for k, v in KEYS.items() if k != "groq_api_key"}
    assert await run_check(handler, "groq", GPT_OSS_120B, keys=keys)
    assert handler.seen == [] and capsys.readouterr().out.startswith("SKIP")


async def test_list_models_prints_only_ids(capsys):
    settings, agents, _, http = setup(groq_server(ids=["zeta", "alpha", "openai/gpt-oss-20b"]))
    assert await smoke.list_models_command(settings, agents, "groq", http) == 0
    out = capsys.readouterr().out
    assert out.splitlines() == ["alpha", "openai/gpt-oss-20b", "zeta"]  # sorted, nothing else
    assert "SECRET-ORG" not in out and FAKE_KEY not in out


async def test_list_models_failure_modes(capsys):
    unauthorized = http_client(lambda r: httpx.Response(401, json={"error": {"message": "k"}}))
    settings = Settings(agents_config=REAL_AGENTS, _env_file=None, **KEYS)
    agents = load_agents(REAL_AGENTS)
    assert await smoke.list_models_command(settings, agents, "groq", unauthorized) == 1
    assert capsys.readouterr().out.strip() == "FAIL unauthorized (HTTP 401)"

    assert await smoke.list_models_command(settings, agents, "nope", unauthorized) == 2
    assert "unknown provider" in capsys.readouterr().out

    no_key = Settings(agents_config=REAL_AGENTS, _env_file=None)
    assert await smoke.list_models_command(no_key, agents, "groq", unauthorized) == 0
    assert capsys.readouterr().out.startswith("SKIP no key")


def test_pairs_cover_every_configured_model_once():
    agents = load_agents(REAL_AGENTS)
    pairs = [(p, m) for p, m, _ in smoke.pairs_to_check(agents, [])]
    assert len(pairs) == len(set(pairs))
    assert ("groq", "openai/gpt-oss-20b") in pairs and ("groq", GPT_OSS_120B) in pairs
    assert all(p != "groq" or m.startswith("openai/gpt-oss") for p, m in pairs)
    assert {p for p, _, _ in smoke.pairs_to_check(agents, ["ollama"])} == {"ollama"}


def test_script_source_never_prints_response_bodies_or_headers():
    src = SCRIPT.read_text(encoding="utf-8")
    assert "resp.text" not in src and "response.text" not in src and "e.body" not in src
