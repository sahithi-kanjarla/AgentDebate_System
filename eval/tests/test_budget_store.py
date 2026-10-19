import json

import pytest

from app.providers.base import CompletionResult, LLMProvider, ProviderError
from eval.budget import (
    Budget,
    BudgetExhausted,
    CountingProvider,
    Ledger,
    estimate_per_question,
    parse_caps,
)
from eval.store import ManifestMismatch, ResultStore


class Stub(LLMProvider):
    name = "openrouter"
    model = "m"

    def __init__(self, cached=False, attempts=1, error=None):
        self.cached, self.attempts, self.error, self.calls = cached, attempts, error, 0

    async def complete(self, messages, json_mode=True):
        self.calls += 1
        if self.error:
            raise self.error
        return CompletionResult(
            text="{}",
            tokens_in=1,
            tokens_out=1,
            latency_ms=1,
            attempts=0 if self.cached else self.attempts,
            cached=self.cached,
        )


def budget(tmp_path, day=lambda: "2026-01-01", **kw):
    return Budget(Ledger(tmp_path / "ledger.json"), today=day, **kw)


def test_parse_caps():
    assert parse_caps("openrouter=40, groq=500") == {"openrouter": 40, "groq": 500}
    assert parse_caps("") == {}
    for bad in ("groq", "groq=x", "=3"):
        with pytest.raises(ValueError):
            parse_caps(bad)


async def test_counts_real_requests_not_cache_hits(tmp_path):
    b = budget(tmp_path, provider_caps={"openrouter": 10})
    await CountingProvider(Stub(attempts=3), b, "openrouter").complete([])
    await CountingProvider(Stub(cached=True), b, "openrouter").complete([])
    assert b.used("openrouter") == 3


async def test_failed_attempts_still_count(tmp_path):
    b = budget(tmp_path)
    err = ProviderError("rate_limited (HTTP 429)", category="rate_limited")
    err.attempts = 3
    with pytest.raises(ProviderError):
        await CountingProvider(Stub(error=err), b, "openrouter").complete([])
    assert b.used("openrouter") == 3


async def test_cap_refuses_calls_before_they_reach_the_provider_and_stays_tripped(tmp_path):
    b = budget(tmp_path, provider_caps={"openrouter": 2})
    stub = Stub()
    p = CountingProvider(stub, b, "openrouter")
    await p.complete([])
    await p.complete([])
    with pytest.raises(BudgetExhausted):
        await p.complete([])
    assert stub.calls == 2
    other = CountingProvider(Stub(), b, "groq")  # a tripped budget stops concurrent agents too
    with pytest.raises(BudgetExhausted):
        await other.complete([])


async def test_global_cap_counts_all_providers(tmp_path):
    b = budget(tmp_path, daily_cap=2)
    await CountingProvider(Stub(), b, "openrouter").complete([])
    g = Stub()
    g.name = "groq"
    await CountingProvider(g, b, "groq").complete([])
    with pytest.raises(BudgetExhausted):
        await CountingProvider(Stub(), b, "openrouter").complete([])


async def test_ledger_survives_restart_and_resets_with_the_date(tmp_path):
    day = ["2026-01-01"]
    b = budget(tmp_path, day=lambda: day[0], provider_caps={"openrouter": 1})
    await CountingProvider(Stub(), b, "openrouter").complete([])
    b2 = budget(tmp_path, day=lambda: day[0], provider_caps={"openrouter": 1})
    assert b2.used("openrouter") == 1 and b2.reason_blocked("openrouter")
    day[0] = "2026-01-02"
    assert b2.used("openrouter") == 0 and b2.reason_blocked("openrouter") is None
    assert json.loads((tmp_path / "ledger.json").read_text())["2026-01-01"] == {"openrouter": 1}


def test_zero_means_no_cap(tmp_path):
    b = budget(tmp_path, provider_caps={"groq": 0})
    assert b.caps == {}


def test_can_start_uses_the_minimum_needed_calls(tmp_path):
    b = budget(tmp_path, provider_caps={"openrouter": 5}, daily_cap=20)
    assert b.can_start({"openrouter": 2, "groq": 7}) is None
    b.record("openrouter", 4)
    assert "openrouter" in b.can_start({"openrouter": 2})
    b2 = budget(tmp_path / "x", daily_cap=3)
    assert "global" in b2.can_start({"groq": 4})


def test_estimate_per_question_for_the_real_lineup():
    from app.core.settings import BACKEND_DIR, load_agents

    agents = load_agents(BACKEND_DIR / "config" / "agents.yaml")
    est = estimate_per_question(agents, rounds=3, min_critique_rounds=1)
    assert est["gemini"] == (2, 4) and est["openrouter"] == (2, 4)
    assert est["groq"] == (2 + 1, 4 + 2)  # debater_2 rounds + the judge (C and D)


# --- store ---


def test_atomic_save_and_done_ids_ignore_partial_files(tmp_path):
    store = ResultStore(tmp_path / "run")
    store.save_question({"qid": "a", "x": 1})
    (store.questions_dir / "b.json").write_text('{"qid": "b", "trunc', encoding="utf-8")
    (store.questions_dir / "c.json.tmp").write_text("{}", encoding="utf-8")
    assert store.done_ids() == {"a"}
    assert [r["qid"] for r in store.load_questions()] == ["a"]


def test_manifest_mismatch_is_refused_unless_forced(tmp_path):
    store = ResultStore(tmp_path / "run")
    assert store.check_config({"seed": 42}, force=False) is None  # nothing yet
    store.write_manifest({"config": {"seed": 42, "early_stop": True}})
    assert store.check_config({"seed": 42, "early_stop": True}, force=False)
    with pytest.raises(ManifestMismatch, match="early_stop"):
        store.check_config({"seed": 42, "early_stop": False}, force=False)
    assert store.check_config({"seed": 42, "early_stop": False}, force=True)
