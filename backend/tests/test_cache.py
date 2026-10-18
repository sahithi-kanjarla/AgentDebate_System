import pytest

from app.db import cache
from app.db.session import init_db, make_engine
from app.providers.base import Message, ProviderError
from app.providers.cached import CachedProvider
from tests.fakes import MSGS, StubProvider


@pytest.fixture
def engine(tmp_path):
    eng = make_engine(f"sqlite:///{tmp_path / 'cache.db'}")
    init_db(eng)
    yield eng
    eng.dispose()


async def test_miss_then_hit_skips_the_provider(engine):
    inner = StubProvider("a", text="answer")
    p = CachedProvider(inner, engine)
    first = await p.complete(MSGS)
    second = await p.complete(MSGS)
    assert inner.calls == 1
    assert not first.cached and second.cached
    assert second.text == "answer" and (second.tokens_in, second.tokens_out) == (3, 2)
    assert second.latency_ms == 0 and second.attempts == 0
    assert (second.provider, second.model) == ("a", "stub-model")


async def test_cache_survives_a_new_engine_and_provider(tmp_path):
    url = f"sqlite:///{tmp_path / 'persist.db'}"
    e1 = make_engine(url)
    init_db(e1)
    await CachedProvider(StubProvider("a", text="kept"), e1).complete(MSGS)
    e1.dispose()

    e2 = make_engine(url)
    inner = StubProvider("a", text="NEW")
    result = await CachedProvider(inner, e2).complete(MSGS)
    e2.dispose()
    assert result.cached and result.text == "kept" and inner.calls == 0


@pytest.mark.parametrize(
    "variant",
    [
        {"provider": "b"},
        {"model": "other-model"},
        {"params": {"temperature": 0.9}},
        {"messages": [Message(role="user", content="a different question")]},
        {"json_mode": False},
    ],
    ids=["provider", "model", "params", "messages", "json_mode"],
)
async def test_key_changes_with_every_input(engine, variant):
    base = StubProvider("a", text="base", params={"temperature": 0.1})
    await CachedProvider(base, engine).complete(MSGS)

    other = StubProvider(
        variant.get("provider", "a"),
        text="other",
        model=variant.get("model", "stub-model"),
        params=variant.get("params", {"temperature": 0.1}),
    )
    result = await CachedProvider(other, engine).complete(
        variant.get("messages", MSGS), variant.get("json_mode", True)
    )
    assert not result.cached and result.text == "other" and other.calls == 1


async def test_errors_are_not_cached(engine):
    inner = StubProvider(
        "a", error=ProviderError("server_error (HTTP 500)", category="server_error")
    )
    p = CachedProvider(inner, engine)
    with pytest.raises(ProviderError):
        await p.complete(MSGS)
    inner.error = None
    result = await p.complete(MSGS)
    assert not result.cached and inner.calls == 2
    assert (await p.complete(MSGS)).cached


async def test_broken_cache_never_breaks_a_call(engine, monkeypatch):
    def explode(*args, **kwargs):
        raise RuntimeError("db is on fire")

    monkeypatch.setattr(cache, "get", explode)
    monkeypatch.setattr(cache, "put", explode)
    inner = StubProvider("a", text="still works")
    result = await CachedProvider(inner, engine).complete(MSGS)
    assert result.text == "still works" and not result.cached


def test_key_is_stable_and_dict_order_independent():
    msgs = [m.model_dump() for m in MSGS]
    k1 = cache.make_key("p", "m", {"a": 1, "b": 2}, msgs, True)
    k2 = cache.make_key("p", "m", {"b": 2, "a": 1}, msgs, True)
    assert k1 == k2 and len(k1) == 64
    assert k1 != cache.make_key("p", "m", {"a": 1, "b": 2}, msgs, False)


def test_concurrent_identical_put_is_harmless(engine):
    cache.put(engine, "k", text="t", tokens_in=1, tokens_out=1, provider="p", model="m")
    cache.put(engine, "k", text="t2", tokens_in=2, tokens_out=2, provider="p", model="m")
    assert cache.get(engine, "k")["text"] == "t2"
