from abc import ABC, abstractmethod
from typing import Any, Literal

from pydantic import BaseModel


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class CompletionResult(BaseModel):
    text: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    # Who actually answered. Providers that know fill these in; blank means "as configured".
    provider: str = ""
    model: str = ""
    attempts: int = 1  # HTTP attempts made, including retries
    cached: bool = False
    fallback_used: bool = False


class ProviderError(Exception):
    """A provider call failed.

    `str(error)` is always safe to show users and log: a short category plus an HTTP status,
    never a response body. `detail` may hold provider text and is for internal decisions only.
    """

    def __init__(
        self,
        message: str,
        recoverable: bool = True,
        *,
        retryable: bool = False,
        retry_after: float | None = None,
        status: int | None = None,
        category: str = "error",
        detail: str = "",
        code: str | None = None,
        error_type: str | None = None,
    ) -> None:
        super().__init__(message)
        self.recoverable = recoverable
        self.retryable = retryable
        self.retry_after = retry_after
        self.status = status
        self.category = category
        self.detail = detail
        self.code = code  # provider's machine-readable error code, e.g. json_validate_failed
        self.error_type = error_type  # provider's error "type" field
        self.attempts = 1


class LLMProvider(ABC):
    # Identity used for logging, caching and recording who answered. Subclasses set these.
    name: str = ""
    model: str = ""

    @abstractmethod
    async def complete(self, messages: list[Message], json_mode: bool = True) -> CompletionResult:
        """Return the model's reply, or raise ProviderError."""

    def cache_params(self) -> dict[str, Any]:
        """Generation settings that change the answer and therefore belong in the cache key."""
        return {}

    async def is_reachable(self) -> bool:
        """Cheap health check used when no ProviderRegistry is available (tests, mock demo)."""
        return True
