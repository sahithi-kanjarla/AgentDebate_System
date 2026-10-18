import asyncio
import random
import time

import httpx
import pytest

from app.providers.base import ProviderError
from app.providers.openai_compat import _retry_after
from app.providers.resilience import RetryPolicy
from tests.fakes import (
    FAKE_KEY,
    MSGS,
    Sleeps,
    body_of,
    error_response,
    make_provider,
    ok_response,
)


async def test_request_shape_and_response_parsing():
    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        return ok_response('{"a": 1}', model="test-model")

    p = make_provider(handler, temperature=0.3, max_tokens=99)
    result = await p.complete(MSGS, json_mode=True)

    req = seen[0]
    assert str(req.url) == "https://api.test/v1/chat/completions"
    assert req.headers["authorization"] == f"Bearer {FAKE_KEY}"
    body = body_of(req)
    assert body["model"] == "test-model" and body["temperature"] == 0.3
    assert body["max_tokens"] == 99
    assert body["response_format"] == {"type": "json_object"}
    assert [m["role"] for m in body["messages"]] == ["system", "user"]

    assert result.text == '{"a": 1}'
    assert (result.tokens_in, result.tokens_out) == (11, 7)
    assert (result.provider, result.model, result.attempts) == ("testprov", "test-model", 1)
    assert not result.cached and not result.fallback_used


async def test_no_response_format_when_json_mode_off_or_disabled():
    bodies = []

    def handler(request):
        bodies.append(body_of(request))
        return ok_response()

    await make_provider(handler).complete(MSGS, json_mode=False)
    await make_provider(handler, json_mode="none").complete(MSGS, json_mode=True)
    assert all("response_format" not in b for b in bodies) and len(bodies) == 2


async def test_missing_usage_is_estimated():
    p = make_provider(lambda r: ok_response("x" * 40, usage=False))
    result = await p.complete(MSGS)
    expected_in = sum(len(m.content) for m in MSGS) // 4
    assert result.tokens_in == expected_in and result.tokens_out == 10


@pytest.mark.parametrize("content", [None, ""])
async def test_empty_content_is_an_error(content):
    p = make_provider(
        lambda r: httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
    )
    with pytest.raises(ProviderError) as exc:
        await p.complete(MSGS)
    assert exc.value.category == "empty_response"


async def test_retries_5xx_with_backoff_then_succeeds():
    calls = []

    def handler(request):
        calls.append(1)
        return error_response(503) if len(calls) < 3 else ok_response()

    sleeps = Sleeps()
    result = await make_provider(handler, sleeps=sleeps).complete(MSGS)
    assert result.attempts == 3 and len(calls) == 3
    assert len(sleeps.delays) == 2
    assert 0 <= sleeps.delays[0] <= 1.0 and 0 <= sleeps.delays[1] <= 2.0  # base 1s, doubling


async def test_gives_up_after_max_attempts():
    calls = []

    def handler(request):
        calls.append(1)
        return error_response(500, "internal secret detail")

    sleeps = Sleeps()
    p = make_provider(handler, sleeps=sleeps, policy=RetryPolicy(max_attempts=3))
    with pytest.raises(ProviderError) as exc:
        await p.complete(MSGS)
    e = exc.value
    assert len(calls) == 3 and e.attempts == 3 and len(sleeps.delays) == 2
    assert e.category == "server_error" and e.status == 500 and e.retryable


async def test_429_honors_retry_after_header():
    calls = []

    def handler(request):
        calls.append(1)
        return (
            error_response(429, headers={"retry-after": "2"}) if len(calls) == 1 else ok_response()
        )

    sleeps = Sleeps()
    result = await make_provider(handler, sleeps=sleeps).complete(MSGS)
    assert sleeps.delays == [2.0] and result.attempts == 2


async def test_429_with_long_retry_after_gives_up_immediately_for_fallback():
    calls = []

    def handler(request):
        calls.append(1)
        return error_response(429, headers={"retry-after": "3600"})

    sleeps = Sleeps()
    with pytest.raises(ProviderError) as exc:
        await make_provider(handler, sleeps=sleeps).complete(MSGS)
    assert len(calls) == 1 and sleeps.delays == []
    assert exc.value.category == "rate_limited" and exc.value.retry_after == 3600


@pytest.mark.parametrize(
    "status,category",
    [
        (400, "bad_request"),
        (401, "unauthorized"),
        (403, "unauthorized"),
        (404, "model_not_found"),
        (402, "payment_required"),
    ],
)
async def test_client_errors_are_not_retried(status, category):
    calls = []

    def handler(request):
        calls.append(1)
        return error_response(status)

    with pytest.raises(ProviderError) as exc:
        await make_provider(handler).complete(MSGS)
    assert len(calls) == 1 and not exc.value.retryable
    assert exc.value.category == category and exc.value.status == status


@pytest.mark.parametrize(
    "exc_factory,category",
    [
        (lambda r: httpx.ReadTimeout("slow", request=r), "timeout"),
        (lambda r: httpx.ConnectError("refused", request=r), "unreachable"),
    ],
)
async def test_timeouts_and_connection_errors_are_retried(exc_factory, category):
    calls = []

    def handler(request):
        calls.append(1)
        raise exc_factory(request)

    with pytest.raises(ProviderError) as exc:
        await make_provider(handler).complete(MSGS)
    assert len(calls) == 3 and exc.value.category == category


async def test_error_message_never_contains_response_body_or_key():
    p = make_provider(lambda r: error_response(400, f"org_SECRET leaked {FAKE_KEY}"))
    with pytest.raises(ProviderError) as exc:
        await p.complete(MSGS)
    assert "org_SECRET" not in str(exc.value) and FAKE_KEY not in str(exc.value)
    assert str(exc.value) == "bad_request (HTTP 400)"


async def test_json_mode_rejected_by_endpoint_is_disabled_and_retried_once():
    bodies = []

    def handler(request):
        body = body_of(request)
        bodies.append(body)
        if "response_format" in body:
            return error_response(400, "Unsupported parameter: response_format")
        return ok_response()

    p = make_provider(handler)
    first = await p.complete(MSGS)
    assert first.attempts == 2 and len(bodies) == 2 and "response_format" not in bodies[1]
    await p.complete(MSGS)  # remembered: no more probing
    assert len(bodies) == 3 and "response_format" not in bodies[2]


async def test_other_400s_do_not_disable_json_mode():
    def handler(request):
        return error_response(400, "context length exceeded")

    p = make_provider(handler)
    with pytest.raises(ProviderError):
        await p.complete(MSGS)
    assert p._json_mode_enabled


async def test_concurrency_is_capped_by_the_shared_semaphore():
    in_flight = 0
    peak = 0

    async def handler(request):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.02)
        in_flight -= 1
        return ok_response()

    p = make_provider(handler, semaphore=asyncio.Semaphore(2))
    await asyncio.gather(*(p.complete(MSGS) for _ in range(8)))
    assert peak == 2


async def test_semaphore_is_released_while_backing_off():
    # One slot; a retrying call must not hold it during its backoff sleep.
    state = {"n": 0}

    def handler(request):
        state["n"] += 1
        return error_response(503) if state["n"] == 1 else ok_response()

    release = asyncio.Event()
    entered_sleep = asyncio.Event()

    async def sleep(delay):
        entered_sleep.set()
        await release.wait()

    p = make_provider(handler, semaphore=asyncio.Semaphore(1))
    p._sleep = sleep
    first = asyncio.create_task(p.complete(MSGS))
    await entered_sleep.wait()
    assert not p._semaphore.locked()
    release.set()
    assert (await first).attempts == 2


def test_backoff_is_exponential_with_full_jitter_and_capped():
    policy = RetryPolicy(base_delay_s=1.0, max_delay_s=8.0)
    rng = random.Random(1)
    for attempt, cap in [(1, 1), (2, 2), (3, 4), (4, 8), (5, 8), (9, 8)]:
        samples = [policy.backoff(attempt, rng) for _ in range(200)]
        assert 0 <= min(samples) and max(samples) <= cap
        assert max(samples) > cap * 0.7  # actually spread over the range, not constant


def _resp(headers: dict[str, str]) -> httpx.Response:
    return httpx.Response(429, headers=headers)


def test_retry_after_parsing():
    assert _retry_after(_resp({"retry-after": "5"})) == 5.0
    assert _retry_after(_resp({"retry-after": "junk"})) is None
    assert _retry_after(_resp({})) is None
    reset_ms = str(int((time.time() + 10) * 1000))
    wait = _retry_after(_resp({"x-ratelimit-reset": reset_ms}))
    assert wait is not None and 8 < wait <= 10
    assert _retry_after(_resp({"x-ratelimit-reset": "1"})) is None  # long past: ignore


# --- Groq gpt-oss: HTTP 400 "Failed to generate JSON" and reasoning-model request options ---

JSON_VALIDATE_FAILED = {
    "error": {
        "message": "Failed to generate JSON. Please adjust your prompt. "
        "See 'failed_generation' for more details.",
        "type": "invalid_request_error",
        "code": "json_validate_failed",
        "failed_generation": "SECRET-MODEL-OUTPUT",
    }
}


def groq_style_handler(calls):
    """400 json_validate_failed when response_format is sent, a normal reply otherwise."""

    def handler(request):
        body = body_of(request)
        calls.append(body)
        if "response_format" in body:
            return httpx.Response(400, json=JSON_VALIDATE_FAILED)
        return ok_response('{"ok": true}')

    return handler


async def test_json_validate_failed_retries_once_without_json_mode_but_keeps_it_on():
    calls: list[dict] = []
    p = make_provider(groq_style_handler(calls))
    first = await p.complete(MSGS)
    assert first.text == '{"ok": true}' and first.attempts == 2
    assert "response_format" in calls[0] and "response_format" not in calls[1]
    # Unlike "response_format unsupported", this is per-call: JSON mode stays enabled.
    assert p._json_mode_enabled
    await p.complete(MSGS)
    assert "response_format" in calls[2]  # tried JSON mode again


async def test_json_validate_failed_detected_from_the_message_alone():
    def handler(request):
        if "response_format" in body_of(request):
            return error_response(400, "Failed to generate JSON. Please adjust your prompt.")
        return ok_response()

    result = await make_provider(handler).complete(MSGS)
    assert result.attempts == 2


async def test_json_validate_failed_on_the_unconstrained_retry_too_raises_total_attempts():
    p = make_provider(lambda r: httpx.Response(400, json=JSON_VALIDATE_FAILED))
    with pytest.raises(ProviderError) as exc:
        await p.complete(MSGS)
    e = exc.value
    assert e.category == "bad_request" and e.status == 400 and e.attempts == 2
    assert e.code == "json_validate_failed" and e.error_type == "invalid_request_error"
    assert "SECRET-MODEL-OUTPUT" not in str(e) + e.detail  # failed_generation is never kept


async def test_error_code_and_type_are_captured_from_the_body():
    body = {
        "error": {"message": "gone", "type": "invalid_request_error", "code": "model_not_found"}
    }
    p = make_provider(lambda r: httpx.Response(404, json=body))
    with pytest.raises(ProviderError) as exc:
        await p.complete(MSGS)
    assert (exc.value.code, exc.value.error_type) == ("model_not_found", "invalid_request_error")
    assert exc.value.category == "model_not_found"


async def test_token_param_and_extra_body_are_sent_as_configured():
    bodies = []

    def handler(request):
        bodies.append(body_of(request))
        return ok_response()

    p = make_provider(
        handler,
        max_tokens=1536,
        token_param="max_completion_tokens",
        extra_body={"reasoning_effort": "low"},
    )
    await p.complete(MSGS)
    body = bodies[0]
    assert body["max_completion_tokens"] == 1536 and "max_tokens" not in body
    assert body["reasoning_effort"] == "low"  # extra_body is merged into the top level


async def test_default_token_param_is_max_tokens_and_no_extras():
    bodies = []

    def handler(request):
        bodies.append(body_of(request))
        return ok_response()

    await make_provider(handler, max_tokens=50).complete(MSGS)
    assert bodies[0]["max_tokens"] == 50 and "max_completion_tokens" not in bodies[0]
    assert set(bodies[0]) == {"model", "messages", "temperature", "max_tokens", "response_format"}


async def test_reasoning_model_out_of_tokens_is_reported_as_finish_reason_length():
    def handler(request):
        body = {"choices": [{"message": {"content": ""}, "finish_reason": "length"}]}
        return httpx.Response(200, json=body)

    with pytest.raises(ProviderError) as exc:
        await make_provider(handler).complete(MSGS)
    assert str(exc.value) == "empty_response (finish_reason=length)"


def test_cache_params_include_the_reasoning_options():
    a = make_provider(lambda r: ok_response(), extra_body={"reasoning_effort": "low"})
    b = make_provider(lambda r: ok_response(), extra_body={"reasoning_effort": "high"})
    assert a.cache_params() != b.cache_params()


async def test_detail_is_only_the_error_message_field_never_the_raw_body():
    p = make_provider(lambda r: httpx.Response(400, json=JSON_VALIDATE_FAILED))
    with pytest.raises(ProviderError) as exc:
        await p.complete(MSGS)
    assert exc.value.detail.startswith("Failed to generate JSON")
    assert "Error code" not in exc.value.detail and "{" not in exc.value.detail
