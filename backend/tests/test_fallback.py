import pytest

from app.providers.base import ProviderError
from app.providers.fallback import FallbackProvider, UnavailableProvider
from tests.fakes import MSGS, StubProvider


def fail(category="server_error", **kw) -> ProviderError:
    return ProviderError(f"{category} (HTTP 500)", category=category, detail="provider text", **kw)


async def test_primary_success_is_not_a_fallback():
    primary, backup = StubProvider("a"), StubProvider("b")
    result = await FallbackProvider([primary, backup]).complete(MSGS)
    assert result.provider == "a" and not result.fallback_used
    assert backup.calls == 0


async def test_falls_back_in_order_and_marks_the_result():
    a = StubProvider("a", error=fail())
    b = StubProvider("b", error=fail("rate_limited"))
    c = StubProvider("c", text="from c")
    result = await FallbackProvider([a, b, c]).complete(MSGS)
    assert (result.provider, result.text, result.fallback_used) == ("c", "from c", True)
    assert (a.calls, b.calls, c.calls) == (1, 1, 1)


async def test_non_retryable_errors_also_fall_back():
    # A bad key or retired model ID is exactly when the fallback should take over.
    bad_key = StubProvider(
        "a", error=ProviderError("unauthorized (HTTP 401)", category="unauthorized")
    )
    result = await FallbackProvider([bad_key, StubProvider("b")]).complete(MSGS)
    assert result.provider == "b" and result.fallback_used


async def test_skipped_primary_counts_as_fallback_even_for_the_first_built_leg():
    result = await FallbackProvider([StubProvider("ollama")], primary_skipped=True).complete(MSGS)
    assert result.provider == "ollama" and result.fallback_used


async def test_attempts_include_failed_legs():
    a = StubProvider("a", error=fail())
    a.error.attempts = 3
    b = StubProvider("b", attempts=2)
    result = await FallbackProvider([a, b]).complete(MSGS)
    assert result.attempts == 5


async def test_all_legs_failing_raises_a_safe_aggregate_error():
    chain = [
        StubProvider("a", error=fail("rate_limited")),
        StubProvider("b", error=fail("timeout")),
    ]
    with pytest.raises(ProviderError) as exc:
        await FallbackProvider(chain).complete(MSGS)
    assert str(exc.value) == "all providers failed (rate_limited, timeout)"
    assert exc.value.category == "all_providers_failed"
    assert "provider text" not in str(exc.value)  # raw provider text stays in .detail


def test_empty_chain_rejected():
    with pytest.raises(ValueError):
        FallbackProvider([])


async def test_unavailable_provider_fails_cleanly():
    p = UnavailableProvider("gemini", "m", "no usable provider (missing API keys)")
    assert not await p.is_reachable()
    with pytest.raises(ProviderError, match="no usable provider"):
        await p.complete(MSGS)
