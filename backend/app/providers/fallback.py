import logging

from app.providers.base import CompletionResult, LLMProvider, Message, ProviderError

log = logging.getLogger(__name__)


class FallbackProvider(LLMProvider):
    """Tries each provider in order; the first success wins.

    A leg is abandoned only after its own retries are exhausted. Any ProviderError counts,
    including non-retryable ones such as a bad key or a retired model ID. The result is marked
    `fallback_used` when anything other than the configured primary answered, which includes
    the case where the primary was skipped because it has no API key.
    """

    def __init__(self, chain: list[LLMProvider], *, primary_skipped: bool = False) -> None:
        if not chain:
            raise ValueError("fallback chain must not be empty")
        self.chain = chain
        self._offset = 1 if primary_skipped else 0
        self.name = chain[0].name
        self.model = chain[0].model

    async def is_reachable(self) -> bool:
        return await self.chain[0].is_reachable()

    async def complete(self, messages: list[Message], json_mode: bool = True) -> CompletionResult:
        errors: list[ProviderError] = []
        for i, leg in enumerate(self.chain):
            try:
                result = await leg.complete(messages, json_mode)
            except ProviderError as e:
                errors.append(e)
                nxt = self.chain[i + 1] if i + 1 < len(self.chain) else None
                log.warning(
                    "llm_fallback",
                    extra={
                        "provider": leg.name,
                        "model": leg.model,
                        "error_category": e.category,
                        "http_status": e.status,
                        "next_provider": nxt.name if nxt else None,
                    },
                )
                continue
            used = i + self._offset > 0
            return result.model_copy(
                update={
                    "fallback_used": used or result.fallback_used,
                    # Failed legs still spent requests against their quotas.
                    "attempts": result.attempts + sum(e.attempts for e in errors),
                }
            )
        categories = ", ".join(e.category for e in errors)
        raise ProviderError(
            f"all providers failed ({categories})",
            category="all_providers_failed",
            detail=" | ".join(e.detail for e in errors if e.detail),
        )


class UnavailableProvider(LLMProvider):
    """Stands in for an agent with no usable provider (e.g. every key is missing)."""

    def __init__(self, name: str, model: str, reason: str) -> None:
        self.name = name
        self.model = model
        self._reason = reason

    async def is_reachable(self) -> bool:
        return False

    async def complete(self, messages: list[Message], json_mode: bool = True) -> CompletionResult:
        raise ProviderError(self._reason, category="no_provider")
