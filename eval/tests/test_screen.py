"""The difficulty screen on scripted providers and a generated 5 x 40 MMLU-Pro file. No network."""

import asyncio
import json
from pathlib import Path

import pytest

from app.core.settings import load_agents
from app.providers.base import ProviderError
from eval import mmlupro, screen
from eval.mmlupro import MMLUProScreen, select, selection_path
from eval.screen import interleaved, main, summarize, verdict
from eval.tests.helpers import factory
from eval.tests.mmlu_helpers import MMLU_CATEGORIES, mmlu_rows, write_mmlu_data

CONFIG = Path(mmlupro.__file__).parent / "config" / "mmlupro_agents.yaml"
FLOOR = "debater_1-gemini-3.1-flash-lite"
GPT = "debater_2-openai_gpt-oss-20b"


def gold_of_qid(qid: int) -> str:
    return "ABCD"[(qid % 1000) % 4]


def other(letter: str) -> str:
    return "ABCD"[("ABCD".index(letter) + 1) % 4]


def behave(c):
    """debater_1 (floor): right on 6 of every 10 questions. debater_2 (ceiling): right on
    everything except physics, where it is always wrong, and answers "Option X" once in a while."""
    gold = gold_of_qid(c.q)
    category = MMLU_CATEGORIES[c.q // 1000]
    if c.agent_id == "debater_1":
        return gold if (c.q % 10) < 6 else other(gold)
    if category == "physics":
        return other(gold)
    if c.q % 25 == 7:
        return "Option " + gold
    return f"({gold})."


@pytest.fixture
def world(tmp_path):
    data_dir = tmp_path / "data"
    write_mmlu_data(data_dir, mmlu_rows(40))
    select("holdout", mmlupro.HOLDOUT_SEED, data_dir)
    select("screen", 42, data_dir)
    return data_dir


class Run:
    def __init__(self, tmp_path, settings, data_dir, behave=behave):
        self.tmp_path, self.settings, self.data_dir = tmp_path, settings, data_dir
        self.factory = factory(behave)
        self.out: list[str] = []
        self.sleeps: list[float] = []

    async def _sleep(self, s):
        self.sleeps.append(s)

    def __call__(self, *argv, **kw):
        return main(
            ["--config", str(CONFIG), "--yes", "--sleep-between-s", "3", *argv],
            provider_factory=self.factory,
            dataset=MMLUProScreen(self.data_dir, selection_path("screen", 42, self.data_dir)),
            settings=self.settings,
            sleep=self._sleep,
            today=lambda: "2026-01-01",
            results_dir=self.tmp_path / "results",
            cache_dir=self.tmp_path / "cache",
            data_dir=self.data_dir,
            out=self.out.append,
            **kw,
        )

    @property
    def root(self):
        return self.tmp_path / "results" / "mmlupro-screen-s42"

    def records(self, folder):
        return [
            json.loads(p.read_text("utf-8"))
            for p in sorted((self.root / folder / "questions").glob("*.json"))
        ]

    def calls(self, agent):
        return self.factory.made[agent].calls

    def sent_nothing(self):
        made = getattr(self.factory, "made", {})
        return all(not p.calls for p in made.values())

    @property
    def text(self):
        return "\n".join(self.out)


@pytest.fixture
def run(tmp_path, settings, world):
    return Run(tmp_path, settings, world)


def test_both_models_screen_all_sixty_questions_one_call_each(run):
    assert run() == 0, run.text
    assert len(run.records(FLOOR)) == 60 and len(run.records(GPT)) == 60
    # one call per question per model; no repair needed; the other seats are never called
    assert len(run.calls("debater_1")) == 60 and len(run.calls("debater_2")) == 60
    assert run.calls("debater_3") == [] and run.calls("judge") == []
    assert all(c.role == "debater" and c.round == 0 for c in run.calls("debater_1"))
    ledger = json.loads((run.root / "ledger.json").read_text("utf-8"))
    assert ledger == {"2026-01-01": {"mock": 120}}  # every request counted in the ledger


def test_per_model_and_per_category_accuracy_invalid_and_truncated_are_reported(run):
    run()
    floor, gpt = summarize(run.records(FLOOR)), summarize(run.records(GPT))
    assert floor["n"] == 60 and floor["correct"] == sum(r["correct"] for r in run.records(FLOOR))
    assert all(v["n"] == 12 for v in floor["categories"].values())
    assert gpt["categories"]["physics"]["correct"] == 0
    assert gpt["categories"]["law"]["correct"] > 0
    assert gpt["invalid"] == sum(r["status"] == "invalid" for r in run.records(GPT)) > 0
    assert gpt["truncated"] == 0
    assert "Per category: chemistry" in run.text and "Invalid answers:" in run.text
    assert "debater_1: gemini/gemini-3.1-flash-lite" in run.text
    assert "debater_2: groq/openai/gpt-oss-20b" in run.text


def test_a_category_below_the_floor_is_a_miss_and_comes_with_guidance(run):
    run()
    met, why = verdict(summarize(run.records(GPT)), 60)
    assert not met and any("physics is below 25%" in w for w in why)
    assert "MISSED" in run.text and "new, disjoint screen seed" in run.text


def test_verdict_rules():
    def rec(cat, correct):
        return {
            "category": cat, "correct": correct, "status": "correct" if correct else "wrong",
            "truncated": False, "repair_used": False, "fallback_used": False, "tokens_out": 1,
            "answer": "A",
        }  # fmt: skip

    def screen(per_cat):
        return summarize([rec(c, i < k) for c, k in per_cat.items() for i in range(12)])

    ok = dict.fromkeys(MMLU_CATEGORIES, 6)
    assert verdict(screen(ok), 60) == (True, [])
    assert not verdict(screen(dict.fromkeys(MMLU_CATEGORIES, 3)), 60)[0]  # 25% overall
    assert not verdict(screen(dict.fromkeys(MMLU_CATEGORIES, 10)), 60)[0]  # 83%: too easy
    assert verdict(screen({**ok, "law": 3}), 60)[0]  # 3 of 12 is exactly 25%, not below
    assert not verdict(screen({**ok, "law": 2}), 60)[0]  # 2 of 12 is below
    assert not verdict(summarize([rec("law", True)] * 5), 60)[0]  # partial screen is never a pass


def test_a_cut_off_reply_is_counted_as_truncated_and_wrong(tmp_path, settings, world):
    def cut(c):
        return 'RAW:{"reasoning": "long thinking that never' if c.q % 7 == 0 else behave(c)

    r = Run(tmp_path, settings, world, cut)
    r()
    recs = r.records(FLOOR)
    bad = [x for x in recs if x["truncated"]]
    assert bad and all(not x["correct"] and x["status"] == "missing" for x in bad)
    assert all(x["repair_used"] for x in bad)  # it asked once more, then counted it wrong
    assert summarize(recs)["truncated"] == len(bad)


def test_resume_skips_finished_questions_and_sends_nothing(run, tmp_path, settings, world):
    run()
    again = Run(tmp_path, settings, world)
    again()
    assert "Nothing to do." in again.text
    assert again.sent_nothing()


def test_a_cap_stops_the_screen_cleanly_and_a_rerun_continues(tmp_path, settings, world):
    # "mock" requests are counted; cap them below what 120 calls need
    first = Run(tmp_path, settings, world)
    assert first("--max-calls-per-provider", "mock=70") == 0
    assert "Stopped: budget" in first.text
    done = len(first.records(FLOOR)) + len(first.records(GPT))
    assert 0 < done < 120
    # nothing is lost: the next day, with a higher cap, finishes exactly the rest
    second = Run(tmp_path, settings, world)
    assert second("--max-calls-per-provider", "mock=0") == 0
    assert len(second.records(FLOOR)) == 60 and len(second.records(GPT)) == 60
    sent = len(second.calls("debater_1")) + len(second.calls("debater_2"))
    assert sent == 120 - done


def test_report_only_sends_nothing(run, tmp_path, settings, world):
    run()
    again = Run(tmp_path, settings, world)
    assert again("--report") == 0
    assert "## MMLU-Pro screen" in again.text and again.sent_nothing()


def test_changed_settings_are_refused_on_resume(run, tmp_path, settings, world):
    run()
    again = Run(tmp_path, settings, world)
    assert again("--max-tokens", "999") == 1
    assert "different settings (profile)" in again.text


def test_the_manifest_records_what_the_holdout_guard_will_check(run):
    run()
    cfg = json.loads((run.root / GPT / "manifest.json").read_text("utf-8"))["config"]
    assert cfg["model"] == "openai/gpt-oss-20b" and cfg["provider"] == "groq"
    assert cfg["prompt_suffix"] == mmlupro.PROMPT_SUFFIX and cfg["allow_fallback"] is False
    assert cfg["extractor"] == mmlupro.extractor_fingerprint()
    assert cfg["agents_fingerprint"] and cfg["profile"]["max_tokens"] == 2048


def test_questions_are_interleaved_across_categories(world):
    qs = interleaved(MMLUProScreen(world, selection_path("screen", 42, world)).load())
    assert [q.meta["category"] for q in qs[:5]] == list(MMLU_CATEGORIES)
    assert len(qs) == 60


def test_unknown_agent_is_refused(run):
    assert run("--agents", "debater_9") == 1 and "unknown agent id" in run.text


def test_the_eval_config_is_what_the_plan_says():
    agents = load_agents(CONFIG)
    got = {a.id: (a.provider, a.model) for a in agents.all_agents()}
    assert got == {
        "debater_1": ("gemini", "gemini-3.1-flash-lite"),
        "debater_2": ("groq", "openai/gpt-oss-20b"),
        "debater_3": ("mistral", "ministral-14b-2512"),
        "judge": ("groq", "openai/gpt-oss-20b"),
    }
    assert all(not a.fallbacks for a in agents.all_agents())
    opts = agents.providers["groq"].model_options["openai/gpt-oss-20b"]
    assert opts.extra_body == {"reasoning_effort": "low"}


def test_debater_3_is_paced_and_capped_on_mistral():
    from eval.budget import DEFAULT_PROVIDER_CAPS

    mistral = load_agents(CONFIG).providers["mistral"]
    assert mistral.rpm == 20 and mistral.json_mode == "json_object" and mistral.max_concurrency == 1
    assert DEFAULT_PROVIDER_CAPS["mistral"] > 0  # an unlisted provider would be uncapped


def test_json_mode_is_off_only_for_debater_1s_provider():
    agents = load_agents(CONFIG)
    off = {name for name, p in agents.providers.items() if p.json_mode == "none"}
    assert off == {"gemini"}
    assert [a.id for a in agents.all_agents() if a.provider in off] == ["debater_1"]


def test_the_app_config_is_untouched():
    app = load_agents(mmlupro.DATA_DIR.parents[1] / "backend" / "config" / "agents.yaml")
    assert app.debaters[0].model != "gemini-3.1-flash-lite"


# --- failures: the real error is shown, and one failure never aborts the rest ---


def flaky(first_failure):
    """debater_1 raises `first_failure()` on questions 0 mod 7 and answers the rest."""

    def f(c):
        if c.agent_id == "debater_1" and c.q % 7 == 0:
            return first_failure()
        return behave(c)

    return f


def test_a_failing_question_is_skipped_not_fatal_and_the_error_is_shown(tmp_path, settings, world):
    r = Run(tmp_path, settings, world, flaky(lambda: ProviderError("Gemini HTTP 500 upstream")))
    assert r() == 0, r.text
    bad = {q for q in range(1000 * 5) if q % 7 == 0}
    skipped = json.loads((r.root / FLOOR / "skipped.json").read_text("utf-8"))
    assert skipped and all("Gemini HTTP 500 upstream" in v for v in skipped.values())
    assert "attempt 3/3 failed: Gemini HTTP 500 upstream" in r.text
    assert "Interrupted" not in r.text
    done = len(r.records(FLOOR))
    assert 0 < done < 60 and done + len(skipped) == 60 and bad  # the rest carried on
    assert len(r.records(GPT)) == 60  # and the other agent was not touched
    # the failed questions are retried on the next run, and only those
    again = Run(tmp_path, settings, world, behave)
    assert again() == 0
    assert len(again.records(FLOOR)) == 60
    assert len(again.calls("debater_1")) == len(skipped) and again.calls("debater_2") == []


def test_an_unexpected_exception_shows_its_type_and_message_and_spares_the_other_agent(
    tmp_path, settings, world
):
    r = Run(tmp_path, settings, world, flaky(lambda: RuntimeError("kaboom")))
    assert r() == 0, r.text
    assert "RuntimeError: kaboom" in r.text and "Interrupted" not in r.text
    assert len(r.records(GPT)) == 60


def test_an_agent_that_dies_outright_does_not_stop_the_next_one(
    tmp_path, settings, world, monkeypatch
):
    real = screen.screen_agent

    async def dying(cfg, *a, **kw):
        if cfg.id == "debater_1":
            raise ValueError("provider exploded")
        return await real(cfg, *a, **kw)

    monkeypatch.setattr(screen, "screen_agent", dying)
    r = Run(tmp_path, settings, world)
    assert r() == 0, r.text
    assert "debater_1 failed: ValueError: provider exploded" in r.text
    assert "Stopped: error" in r.text
    assert len(r.records(GPT)) == 60


def test_only_a_real_keyboard_interrupt_is_reported_as_interrupted(tmp_path, settings, world):
    def boom(exc):
        def make(agents):
            raise exc

        return make

    real = Run(tmp_path, settings, world)
    real.factory = boom(KeyboardInterrupt())
    assert real() == 130 and "Interrupted" in real.text

    other_exc = Run(tmp_path, settings, world)
    other_exc.factory = boom(OSError("socket closed"))
    assert other_exc() == 1
    assert "OSError: socket closed" in other_exc.text and "Interrupted" not in other_exc.text

    cancelled = Run(tmp_path, settings, world)
    cancelled.factory = boom(asyncio.CancelledError())
    assert cancelled() == 1 and "not a keypress" in cancelled.text


def test_describe_scrubs_secrets():
    msg = screen.describe(RuntimeError("bad key sk-secret-123 here"), ["sk-secret-123"])
    assert msg.startswith("RuntimeError:") and "sk-secret-123" not in msg
