from abc import ABC, abstractmethod
from typing import Literal

from pydantic import BaseModel


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class CompletionResult(BaseModel):
    text: str
    tokens_in: int
    tokens_out: int
    latency_ms: int


class ProviderError(Exception):
    """A provider call failed. `recoverable` hints whether a retry or fallback may help."""

    def __init__(self, message: str, recoverable: bool = True) -> None:
        super().__init__(message)
        self.recoverable = recoverable


class LLMProvider(ABC):
    @abstractmethod
    async def complete(self, messages: list[Message], json_mode: bool = True) -> CompletionResult:
        """Return the model's reply, or raise ProviderError."""

    async def is_reachable(self) -> bool:
        """Cheap health check for /api/agents. Real providers override this in M2."""
        return True
