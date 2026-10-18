import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import openai
from openai import AsyncOpenAI

from app.providers.base import CompletionResult, LLMProvider, Message, ProviderError
from app.providers.resilience import RetryPolicy, call_with_retries

log = logging.getLogger(__name__)

Sleep = Callable[[float], Awaitable[None]]


def classify_error(exc: Exception) -> ProviderError:
    """Turn an openai SDK exception into a ProviderError with a safe message."""
    if isinstance(exc, openai.APITimeoutError):
        return ProviderError("timeout", retryable=True, category="timeout")
    if isinstance(exc, openai.APIConnectionError):
        return ProviderError("unreachable", retryable=True, category="unreachable")
    if isinstance(exc, openai.APIStatusError):
        status = exc.status_code
        # exc.message is the whole "Error code: 400 - {body}" string, which can include model
        # output (Groq's failed_generation). Take only the error object's own "message" field.
        error_obj = exc.body if isinstance(exc.body, dict) else {}
        detail = str(error_obj.get("message") or "")[:500]
        code, error_type = (
            _str_or_none(getattr(exc, "code", None)),
            _str_or_none(getattr(exc, "type", None)),
        )
        if status == 429:
            return ProviderError(
                "rate_limited (HTTP 429)",
                retryable=True,
                retry_after=_retry_after(exc.response),
                status=status,
                category="rate_limited",
                detail=detail,
                code=code,
                error_type=error_type,
            )
        if status >= 500 or status == 408:
            return ProviderError(
                f"server_error (HTTP {status})",
                retryable=True,
                status=status,
                category="server_error",
                detail=detail,
                code=code,
                error_type=error_type,
            )
        category = {
            400: "bad_request",
            401: "unauthorized",
            402: "payment_required",
            403: "unauthorized",
            404: "model_not_found",
        }.get(status, "client_error")
        return ProviderError(
            f"{category} (HTTP {status})",
            status=status,
            category=category,
            detail=detail,
            code=code,
            error_type=error_type,
        )
    return ProviderError(f"unexpected {type(exc).__name__}", category="unexpected")


def _str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _retry_after(response: httpx.Response) -> float | None:
    """Seconds to wait from Retry-After, or OpenRouter's X-RateLimit-Reset (epoch millis)."""
    raw = response.headers.get("retry-after")
    if raw:
        try:
            return max(float(raw), 0.0)
        except ValueError:
            return None
    reset = response.headers.get("x-ratelimit-reset")
    if reset:
        try:
            wait = float(reset) / 1000 - time.time()
        except ValueError:
            return None
        if 0 <= wait < 3600:  # ignore nonsense values
            return wait
    return None


def _json_rejection(e: ProviderError) -> str | None:
    """Why a 400 was about JSON mode: "unsupported" (never send it), "failed" (this call only)."""
    if e.status != 400:
        return None
    detail = e.detail.lower()
    if "response_format" in detail:
        return "unsupported"
    if e.code == "json_validate_failed" or "failed to generate json" in detail:
        return "failed"
    return None


class OpenAICompatibleProvider(LLMProvider):
    """One model on one OpenAI-compatible endpoint (Gemini, Groq, OpenRouter, Ollama).

    Retries 429/5xx/timeouts with backoff+jitter. Our own retries are used (the SDK's are
    disabled) so every attempt is counted and logged. `semaphore` is shared by all models of
    the same provider to cap concurrent requests.
    """

    def __init__(
        self,
        *,
        name: str,
        model: str,
        base_url: str,
        api_key: str | None,
        temperature: float = 0.6,
        max_tokens: int | None = None,
        token_param: str = "max_tokens",
        extra_body: dict[str, Any] | None = None,
        json_mode: str = "json_object",
        timeout_s: float = 60.0,
        policy: RetryPolicy | None = None,
        semaphore: asyncio.Semaphore | None = None,
        http_client: httpx.AsyncClient | None = None,
        sleep: Sleep = asyncio.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self.name = name
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.token_param = token_param
        self.extra_body = dict(extra_body or {})
        self._json_mode_enabled = json_mode == "json_object"
        self._policy = policy or RetryPolicy()
        self._semaphore = semaphore or asyncio.Semaphore(2)
        self._sleep = sleep
        self._rng = rng or random.Random()
        self._client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key or "not-needed",  # the SDK insists on a value; Ollama ignores it
            http_client=http_client,
            max_retries=0,
            timeout=timeout_s,
        )

    def cache_params(self) -> dict[str, Any]:
        return {
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "extra_body": self.extra_body,  # e.g. reasoning_effort changes the answer
        }

    async def complete(self, messages: list[Message], json_mode: bool = True) -> CompletionResult:
        started = time.monotonic()
        use_json = json_mode and self._json_mode_enabled
        attempts = 0
        try:
            try:
                resp, n = await self._request(messages, use_json)
            except ProviderError as e:
                rejection = _json_rejection(e) if use_json else None
                if rejection is None:
                    raise
                if rejection == "unsupported":
                    # The endpoint does not accept response_format: stop sending it at all.
                    self._json_mode_enabled = False
                    log.warning("json mode rejected; disabled", extra={"provider": self.name})
                else:
                    # The endpoint could not produce valid JSON for *this* prompt (e.g. Groq's
                    # json_validate_failed when a reasoning model runs out of tokens). Retry this
                    # call unconstrained; the parser extracts/repairs the JSON. Keep JSON mode on.
                    log.warning(
                        "json mode failed for this call; retrying without it",
                        extra={"provider": self.name, "error_code": e.code},
                    )
                attempts = e.attempts
                try:
                    resp, n = await self._request(messages, False)
                except ProviderError as e2:
                    e2.attempts += attempts
                    raise
            attempts += n
            result = self._to_result(resp, messages, started, attempts)
        except ProviderError as e:
            self._log("error", started, e.attempts, error_category=e.category, http_status=e.status)
            raise

        self._log("ok", started, attempts, tokens_in=result.tokens_in, tokens_out=result.tokens_out)
        return result

    async def _request(self, messages: list[Message], use_json: bool):
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [m.model_dump() for m in messages],
            "temperature": self.temperature,
        }
        if self.max_tokens:
            kwargs[self.token_param] = self.max_tokens
        if self.extra_body:
            kwargs["extra_body"] = self.extra_body
        if use_json:
            kwargs["response_format"] = {"type": "json_object"}
        return await call_with_retries(
            lambda: self._attempt(kwargs),
            self._policy,
            sleep=self._sleep,
            rng=self._rng,
            label=self.name,
        )

    async def _attempt(self, kwargs: dict[str, Any]):
        async with self._semaphore:  # released during backoff sleeps
            try:
                return await self._client.chat.completions.create(**kwargs)
            except openai.OpenAIError as e:
                raise classify_error(e) from None

    def _to_result(
        self, resp: Any, messages: list[Message], started: float, attempts: int
    ) -> CompletionResult:
        choice = resp.choices[0] if resp.choices else None
        text = choice.message.content if choice else None
        if not text:
            reason = getattr(choice, "finish_reason", None)
            reason = reason if reason in ("length", "stop", "content_filter") else "unknown"
            # finish_reason=length with no content means the token limit was spent (on reasoning).
            raise ProviderError(
                f"empty_response (finish_reason={reason})",
                retryable=False,
                category="empty_response",
                detail=f"finish_reason={reason}",
            )
        usage = getattr(resp, "usage", None)
        tokens_in = getattr(usage, "prompt_tokens", None)
        tokens_out = getattr(usage, "completion_tokens", None)
        return CompletionResult(
            text=text,
            tokens_in=(
                tokens_in if tokens_in is not None else sum(len(m.content) for m in messages) // 4
            ),
            tokens_out=tokens_out if tokens_out is not None else len(text) // 4,
            latency_ms=int((time.monotonic() - started) * 1000),
            provider=self.name,
            model=self.model,
            attempts=attempts,
        )

    def _log(self, status: str, started: float, attempts: int, **extra: Any) -> None:
        log.info(
            "llm_call",
            extra={
                "provider": self.name,
                "model": self.model,
                "status": status,
                "latency_ms": int((time.monotonic() - started) * 1000),
                "attempts": attempts,
                "retries": max(attempts - 1, 0),
                **extra,
            },
        )
