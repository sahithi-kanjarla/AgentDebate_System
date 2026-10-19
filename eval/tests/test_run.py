"""The harness end to end on scripted mock providers. No network, no keys."""

import json

import pytest

from app.core.settings import BACKEND_DIR, load_agents
from app.db.session import init_db, make_engine
from app.providers.base import ProviderError
from app.providers.cached import CachedProvider
from eval.run import main, strip_fallbacks
from eval.tests.helpers import factory, gold_of, standard, write_gsm8k


class Env:
    def __init__(self, tmp_path, settings, behave=standard, **fkw):
        self.tmp_path, self.settings = tmp_path, settings
        self.dataset = write_gsm8k(tmp_path / "gsm8k.jsonl", 5)
        self.factory = factory(behave, **fkw)
        self.out: list[str] = []
        self.sleeps: list[float] = []
        self.day = "2026-01-01"

    async def _sleep(self, s):
        self.sleeps.append(s)

    def run(self, *argv, **kw):
        # a fixed order (seed 42) over 5 questions; tests pick questions by qid, not position
        args = ["--n", "3", "--yes", "--sleep-between-s", "5", *argv]
        return main(
            args,
            provider_factory=kw.get("provider_factory", self.factory),
            dataset=self.dataset,
            settings=self.settings,
            sleep=self._sleep,
            today=lambda: self.day,
            results_dir=self.tmp_path / "results",
            cache_dir=self.tmp_path / "cache",
            data_dir=self.tmp_path / "data",
            out=self.out.append,
        )

    @property
    def run_dir(self):
        return self.tmp_path / "results" / "gsm8k-s42"

    def records(self):
        qdir = self.run_dir / "questions"
        files = qdir.glob("*.json") if qdir.exists() else []
        return {r["qid"]: r for r in (json.loads(p.read_text(encoding="utf-8")) for p in files)}

    def calls(self, agent="debater_1"):
        return self.factory.made[agent].calls  # type: ignore[attr-defined]


@pytest.fixture
def env(tmp_path, settings):
    return Env(tmp_path, settings)


def pin_order(env, ids):
    """Fix the question order so tests can talk about 'the first question'."""
    (env.tmp_path / "data").mkdir(exist_ok=True)
    from eval.datasets import order_path

    sha = env.dataset.source_sha256()
    order = [f"gsm8k-test-{i}" for i in ids] + [
        q.qid for q in env.dataset.load() if q.qid not in {f"gsm8k-test-{i}" for i in ids}
    ]
    order_path("gsm8k", 42, env.tmp_path / "data").write_text(
        json.dumps({"dataset": "gsm8k", "seed": 42, "source_sha256": sha, "order": order}),
        encoding="utf-8",
    )


def test_conditions_for_a_debate_that_fixes_a_wrong_majority(env):
    pin_order(env, [0, 1, 2])
    assert env.run() == 0
    r0 = env.records()["gsm8k-test-0"]
    c = r0["conditions"]
    assert [c[k]["correct"] for k in ("A1", "A2", "A3")] == [True, False, False]
    assert not c["B"]["correct"] and c["B"]["answer"] == "110"  # majority of the two wrong answers
    assert not c["C"]["correct"]  # the judge after one round still sees two wrong answers
    assert c["D"]["correct"] and c["D_vote"]["correct"]
    assert r0["facts"]["rounds_run"] == 2 and r0["facts"]["early_stopped"]
    assert not r0["facts"]["c_equals_d"] and r0["facts"]["prefix_consistent"]
    assert r0["gold"] == "10"


def test_costs_are_taken_from_the_fresh_run(env):
    pin_order(env, [0, 1, 2])
    env.run()
    c = env.records()["gsm8k-test-0"]["conditions"]
    assert c["A1"]["cost"]["api_calls"] == 1
    assert c["B"]["cost"]["api_calls"] == 3
    assert c["C"]["cost"]["api_calls"] == 3 + 3 + 1  # D rounds 0-1 + the C judge call
    assert c["D"]["cost"]["api_calls"] == 3 * 3 + 1  # rounds 0..2 and the judge
    assert c["D"]["cost"]["tokens"] > c["B"]["cost"]["tokens"] > c["A1"]["cost"]["tokens"]


def test_unanimous_question_stops_early_and_c_equals_d_without_a_second_judge_call(env):
    pin_order(env, [1])
    env.run("--n", "1")
    r = env.records()["gsm8k-test-1"]
    assert r["facts"]["rounds_run"] == 1 and r["facts"]["c_equals_d"]
    assert r["conditions"]["C"] == r["conditions"]["D"]
    judge_calls = [c for c in env.calls("judge") if c.role == "judge"]
    assert len(judge_calls) == 1
    assert all(r["conditions"][k]["correct"] for k in ("A1", "A2", "A3", "B", "C", "D"))


def test_three_way_split_never_agrees_and_b_tie_is_recorded(env):
    pin_order(env, [2])
    env.run("--n", "1")
    r = env.records()["gsm8k-test-2"]
    assert r["facts"]["rounds_run"] == 3 and not r["facts"]["early_stopped"]
    assert r["conditions"]["B"]["note"] == "tie"
    assert r["conditions"]["D"]["correct"]  # judge picked the gold answer


def test_resume_skips_finished_questions_and_extends_a_pilot(env):
    pin_order(env, [1, 2, 0])
    assert env.run("--n", "2") == 0
    assert len(env.records()) == 2
    first_calls = len(env.calls("debater_1"))
    env.out.clear()
    assert env.run("--n", "2") == 0  # nothing left
    assert any("Nothing to do" in line for line in env.out)
    assert env.run("--n", "3") == 0  # the pilot's two questions are not run again
    assert len(env.records()) == 3
    new_calls = env.calls("debater_1")  # a fresh provider set: only the new question ran
    assert {c.q for c in new_calls} == {0} and first_calls > 0
    manifest = json.loads((env.run_dir / "manifest.json").read_text())
    assert [s["n"] for s in manifest["sessions"]] == [2, 3]  # "nothing to do" starts no session


def test_partial_or_corrupt_files_are_not_treated_as_done(env):
    pin_order(env, [1])
    qdir = env.run_dir / "questions"
    qdir.mkdir(parents=True)
    (qdir / "gsm8k-test-1.json").write_text('{"qid": "gsm8k-test-1", "cond', encoding="utf-8")
    env.run("--n", "1")
    assert env.records()["gsm8k-test-1"]["conditions"]["D"]["correct"]


def test_changed_settings_are_refused_unless_forced(env):
    pin_order(env, [1])
    env.run("--n", "1")
    env.out.clear()
    assert env.run("--n", "1", "--no-early-stop") == 1
    assert any("early_stop" in line for line in env.out)
    assert env.run("--n", "1", "--no-early-stop", "--force") == 0


def test_dry_run_prints_estimates_and_makes_no_calls(env, tmp_path):
    def boom(agents):
        raise AssertionError("providers must not be built in a dry run")

    pin_order(env, [0, 1, 2])
    assert env.run("--dry-run", provider_factory=boom) == 0
    text = "\n".join(env.out)
    assert "mock" in text and "Dry run" in text and "3 question(s) to do" in text
    assert not (env.run_dir / "manifest.json").exists()


def test_confirmation_prompt_can_abort(env):
    pin_order(env, [1])
    out = []
    code = main(
        ["--n", "1"],
        provider_factory=env.factory,
        dataset=env.dataset,
        settings=env.settings,
        input_fn=lambda prompt: "n",
        results_dir=env.tmp_path / "results",
        data_dir=env.tmp_path / "data",
        out=out.append,
    )
    assert code == 0 and "Aborted." in out and not env.run_dir.exists()


def test_budget_stop_is_clean_discards_the_partial_question_and_resumes_next_day(env):
    pin_order(env, [0, 1, 2])
    # No response cache here, so q0 costs 17 requests (the C run repeats rounds 0-1) and q1 costs 7.
    # q2 may start under a cap of 31 (24 + 7 minimum) but needs 20, so the cap trips mid-question.
    assert env.run("--max-calls-per-provider", "mock=31") == 0
    assert sorted(env.records()) == ["gsm8k-test-0", "gsm8k-test-1"]
    assert any("daily call budget reached" in line for line in env.out)
    assert json.loads((env.run_dir / "ledger.json").read_text())["2026-01-01"]["mock"] == 31
    env.out.clear()
    assert env.run("--max-calls-per-provider", "mock=31") == 0  # same day: stops straight away
    assert any("0 finished this session" in line for line in env.out)
    env.day = "2026-01-02"
    assert env.run("--max-calls-per-provider", "mock=31") == 0
    assert "gsm8k-test-2" in env.records()


def test_global_daily_cap_flag_stops_cleanly(env):
    pin_order(env, [1, 2, 0])
    assert env.run("--max-calls-per-day", "8") == 0
    assert len(env.records()) == 1  # q1 (7 requests) fits, the next does not
    assert any("global" in line for line in env.out)


def test_quota_error_stops_the_run_without_storing_the_question(tmp_path, settings):
    def behave(c):
        if c.q == 2 and c.agent_id == "debater_3":
            return ProviderError("rate_limited (HTTP 429)", category="rate_limited")
        return standard(c)

    env = Env(tmp_path, settings, behave)
    pin_order(env, [1, 2, 0])
    assert env.run() == 0
    assert sorted(env.records()) == ["gsm8k-test-1"]
    assert any("rate-limited" in line for line in env.out)
    assert any("Stopped: quota" in line for line in env.out)


def test_missing_key_style_config_error_stops_cleanly(tmp_path, settings):
    def behave(c):
        return ProviderError("unauthorized (HTTP 401)", category="unauthorized")

    env = Env(tmp_path, settings, behave)
    pin_order(env, [1])
    assert env.run("--n", "1") == 0
    assert env.records() == {}
    assert any("Stopped: config" in line for line in env.out)


def test_a_transient_error_retries_then_skips_and_the_run_carries_on(tmp_path, settings):
    def behave(c):
        if c.q == 1:
            return ProviderError("server_error (HTTP 500)", category="server_error")
        return standard(c)

    env = Env(tmp_path, settings, behave)
    pin_order(env, [1, 0])
    assert env.run("--n", "2") == 0
    assert sorted(env.records()) == ["gsm8k-test-0"]
    skipped = json.loads((env.run_dir / "skipped.json").read_text())
    assert "gsm8k-test-1" in skipped
    assert sum(1 for c in env.calls("debater_1") if c.q == 1 and c.round == 0) == 3  # 3 attempts


def test_unparseable_model_output_is_a_stored_wrong_answer_not_an_abort(tmp_path, settings):
    def behave(c):
        if c.q == 1 and c.agent_id == "debater_2" and c.role == "debater":
            return "RAW:I think it is eleven."
        return standard(c)

    env = Env(tmp_path, settings, behave)
    pin_order(env, [1])
    env.run("--n", "1")
    r = env.records()["gsm8k-test-1"]
    assert r["conditions"]["A2"]["status"] == "missing" and not r["conditions"]["A2"]["correct"]
    assert r["conditions"]["B"]["correct"]  # the two valid votes still carry the majority


def test_non_numeric_answers_are_wrong_even_when_the_number_is_right(tmp_path, settings):
    def behave(c):
        if c.role == "debater" and c.agent_id == "debater_1":
            return f"{gold_of(c.q)} dollars"
        return standard(c)

    env = Env(tmp_path, settings, behave)
    pin_order(env, [1])
    env.run("--n", "1")
    c = env.records()["gsm8k-test-1"]["conditions"]
    assert c["A1"]["status"] == "non_numeric" and not c["A1"]["correct"]
    assert c["B"]["correct"] and c["D"]["correct"]


def test_fallback_use_is_recorded_per_condition(tmp_path, settings):
    env = Env(tmp_path, settings, fallback=lambda c: c.agent_id == "debater_1" and c.q == 0)
    pin_order(env, [0])
    env.run("--n", "1")
    c = env.records()["gsm8k-test-0"]["conditions"]
    assert c["A1"]["fallback"] and not c["A2"]["fallback"]
    assert c["B"]["fallback"] and c["D"]["fallback"]
    assert any(t["fallback_used"] for t in env.records()["gsm8k-test-0"]["turns"])


def test_fallbacks_are_removed_unless_allowed():
    agents = load_agents(BACKEND_DIR / "config" / "agents.yaml")
    assert any(a.fallbacks for a in agents.all_agents())
    assert not any(a.fallbacks for a in strip_fallbacks(agents).all_agents())
    assert any(a.fallbacks for a in agents.all_agents())  # the original is not modified


def test_allow_fallback_is_part_of_the_run_identity(env):
    pin_order(env, [1])
    env.run("--n", "1")
    env.out.clear()
    assert env.run("--n", "1", "--allow-fallback") == 1


def test_c_run_replays_rounds_0_and_1_from_the_response_cache(env, tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'c.db').as_posix()}")
    init_db(engine)

    def cached_factory(agents):
        made = env.factory(agents)
        return {k: CachedProvider(v, engine) for k, v in made.items()}

    pin_order(env, [0])
    env.run("--n", "1", provider_factory=cached_factory)
    # D asked each debater for rounds 0, 1 and 2; the C run reused rounds 0 and 1 from the cache.
    assert len([c for c in env.calls("debater_1")]) == 3
    judge = [c for c in env.calls("judge") if c.role == "judge"]
    assert len(judge) == 2  # the C judge sees a shorter transcript, so it is a real call
    r = env.records()["gsm8k-test-0"]
    assert r["conditions"]["C"]["cost"]["api_calls"] == 7  # D's 6 + the C judge, cache hits free
    assert r["conditions"]["D"]["cost"]["api_calls"] == 10


def test_sleeps_only_after_questions_that_sent_requests(env):
    pin_order(env, [1, 2])
    env.run("--n", "2")
    assert env.sleeps == [5.0]  # between the two questions, not after the last


def test_progress_line_and_summary(env):
    pin_order(env, [1])
    env.run("--n", "1")
    text = "\n".join(env.out)
    assert "[1/1] gsm8k-test-1 gold=11 A1=ok" in text and "Correct so far over 1 question" in text
