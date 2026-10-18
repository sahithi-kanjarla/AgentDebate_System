"""Fake HTTP layer for provider tests. Nothing here opens a socket."""

import json
import random
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.providers.base import CompletionResult, LLMProvider, Message, ProviderError
from app.providers.openai_compat import OpenAICompatibleProvider
from app.providers.resilience import RetryPolicy

FAKE_KEY = "test-key-123"


def chat_response(content: str | None, *, model: str = "m", usage: bool = True) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 1,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }
    if usage:
        body["usage"] = {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}
    return body


def error_response(status: int, message: str = "boom", headers: dict[str, str] | None = None):
    return httpx.Response(
        status, json={"error": {"message": message, "type": "x"}}, headers=headers or {}
    )


def ok_response(content: str = '{"ok": true}', **kw: Any) -> httpx.Response:
    return httpx.Response(200, json=chat_response(content, **kw))


Handler = Callable[[httpx.Request], httpx.Response | Awaitable[httpx.Response]]


def http_client(handler: Handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class Sleeps:
    """Records requested sleeps instead of waiting."""

    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)


def make_provider(
    handler: Handler,
    *,
    sleeps: Sleeps | None = None,
    name: str = "testprov",
    model: str = "test-model",
    **kwargs: Any,
) -> OpenAICompatibleProvider:
    kwargs.setdefault("policy", RetryPolicy())
    return OpenAICompatibleProvider(
        name=name,
        model=model,
        base_url="https://api.test/v1",
        api_key=FAKE_KEY,
        http_client=http_client(handler),
        sleep=sleeps or Sleeps(),
        rng=random.Random(0),
        **kwargs,
    )


MSGS = [
    Message(role="system", content="You are a helpful assistant."),
    Message(role="user", content="SECRET-PROMPT-TEXT: what is 2+2?"),
]


def body_of(request: httpx.Request) -> dict[str, Any]:
    return json.loads(request.content)


class StubProvider(LLMProvider):
    """A scripted provider: returns `text` or raises `error`, and counts calls."""

    def __init__(
        self,
        name: str,
        *,
        text: str = "ok",
        error: ProviderError | None = None,
        model: str = "stub-model",
        attempts: int = 1,
        params: dict[str, Any] | None = None,
    ) -> None:
        self.name = name
        self.model = model
        self.text = text
        self.error = error
        self.attempts = attempts
        self.params = params or {}
        self.calls = 0

    def cache_params(self) -> dict[str, Any]:
        return self.params

    async def complete(self, messages: list[Message], json_mode: bool = True) -> CompletionResult:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return CompletionResult(
            text=self.text,
            tokens_in=3,
            tokens_out=2,
            latency_ms=5,
            provider=self.name,
            model=self.model,
            attempts=self.attempts,
        )
