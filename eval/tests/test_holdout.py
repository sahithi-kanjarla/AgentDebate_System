"""The holdout guard against screens produced by the real eval.screen on scripted providers.
No network, no keys."""

import json
from pathlib import Path

import pytest

from app.core.settings import load_agents
from eval import holdout, mmlupro
from eval.holdout import HoldoutRefused, check_holdout_ready
from eval.holdout import main as holdout_main
from eval.mmlupro import MMLUProHoldout, MMLUProScreen, select, selection_path
from eval.run import apply_profile, strip_fallbacks
from eval.run import main as run_main
from eval.screen import main as screen_main
from eval.tests.helpers import factory
from eval.tests.mmlu_helpers import mmlu_rows, write_mmlu_data

CONFIG = Path(mmlupro.__file__).parent / "config" / "mmlupro_agents.yaml"
FLOOR = "debater_1-gemini-3.1-flash-lite"
GPT = "debater_2-openai_gpt-oss-20b"


def gold_of_qid(qid: int) -> str:
    return "ABCD"[(qid % 1000) % 4]


def on_target(c):
    """Both screened models right on 6 of every 10 questions: inside 40-70%, no weak category."""
    gold = gold_of_qid(c.q)
    return gold if (c.q % 10) < 6 else "ABCD"[("ABCD".index(gold) + 1) % 4]


def too_hard(c):
    return "ABCD"[("ABCD".index(gold_of_qid(c.q)) + 1) % 4]


async def no_sleep(_s):
    return None


@pytest.fixture
def world(tmp_path):
    data_dir = tmp_path / "data"
    write_mmlu_data(data_dir, mmlu_rows(40))
    select("holdout", mmlupro.HOLDOUT_SEED, data_dir)
    select("screen", 42, data_dir)
    return data_dir


def do_screen(tmp_path, settings, data_dir, behave=on_target, *argv):
    out: list[str] = []
    code = screen_main(
        ["--config", str(CONFIG), "--yes", "--sleep-between-s", "1", *argv],
        provider_factory=factory(behave),
        dataset=MMLUProScreen(data_dir, selection_path("screen", 42, data_dir)),
        settings=settings,
        sleep=no_sleep,
        today=lambda: "2026-01-01",
        results_dir=tmp_path / "results",
        cache_dir=tmp_path / "cache",
        data_dir=data_dir,
        out=out.append,
    )
    assert code == 0, out


class Guard:
    """Calls the guard the way eval.run does for the default holdout command."""

    def __init__(self, tmp_path, data_dir):
        self.tmp_path, self.data_dir = tmp_path, data_dir
        self.agents = strip_fallbacks(load_agents(CONFIG))
        self.dataset = MMLUProHoldout(data_dir, selection_path("holdout", 2026, data_dir))

    def __call__(self, agents=None, **kw):
        agents, applied = apply_profile(agents or self.agents, self.dataset.profile, None, {})
        return check_holdout_ready(
            self.dataset,
            agents,
            applied,
            results_dir=self.tmp_path / "results",
            data_dir=self.data_dir,
            **kw,
        )

    def refusal(self, agents=None, **kw) -> str:
        with pytest.raises(HoldoutRefused) as e:
            self(agents, **kw)
        return e.value.render()


@pytest.fixture
def screened(tmp_path, settings, world):
    do_screen(tmp_path, settings, world)
    return Guard(tmp_path, world)


def screen_manifest(tmp_path, folder) -> Path:
    return tmp_path / "results" / "mmlupro-screen-s42" / folder / "manifest.json"


def edit_manifest(tmp_path, folder, **config):
    path = screen_manifest(tmp_path, folder)
    m = json.loads(path.read_text("utf-8"))
    m["config"].update(config)
    path.write_text(json.dumps(m), encoding="utf-8")


# --- the guard ---


def test_a_finished_matching_screen_passes_and_returns_the_pin(screened):
    pin = screened()
    assert pin["screen_run"] == "mmlupro-screen-s42" and not pin["accepted_missed"]
    assert set(pin["agents"]) == {"debater_1", "debater_2"}
    assert all(a["n"] == 60 and a["target_met"] for a in pin["agents"].values())
    assert pin["agents"]["debater_1"]["extractor"] == mmlupro.extractor_fingerprint()


def test_no_screen_at_all_is_refused(tmp_path, world):
    assert "no screen results" in Guard(tmp_path, world).refusal()


def test_a_missing_agent_folder_is_refused(screened, tmp_path):
    (screen_manifest(tmp_path, GPT)).unlink()
    assert "debater_2: no screen manifest" in screened.refusal()


def test_an_unfinished_screen_is_refused(screened, tmp_path):
    victim = next(
        (tmp_path / "results" / "mmlupro-screen-s42" / FLOOR / "questions").glob("*.json")
    )
    victim.unlink()
    text = screened.refusal()
    assert "debater_1: 59 of 60 screen questions finished, 1 missing" in text
    assert "debater_2" not in text  # the other model is complete


def test_a_partial_result_file_does_not_count(screened, tmp_path):
    victim = next((tmp_path / "results" / "mmlupro-screen-s42" / GPT / "questions").glob("*.json"))
    victim.write_text('{"qid": "x"', encoding="utf-8")  # cut off mid-write
    assert "debater_2: 59 of 60" in screened.refusal()


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("prompt_suffix_sha256", "0" * 64),
        ("prompt_suffix", "Reply with a letter."),
        ("extractor", "deadbeefdeadbeef"),
        ("agents_fingerprint", "0123456789abcdef"),
        ("source_sha256", "f" * 64),
        ("model", "some-other-model"),
        ("max_tokens", 4096),
        ("profile", {"max_tokens": 4096}),
        ("allow_fallback", True),
    ],
)
def test_every_pinned_hash_and_setting_must_match(screened, tmp_path, key, value):
    edit_manifest(tmp_path, FLOOR, **{key: value})
    text = screened.refusal()
    assert f"debater_1: screen {key} was" in text and "the holdout would use" in text


def test_changing_the_config_after_the_screen_is_refused(screened):
    changed = screened.agents.model_copy(deep=True)
    changed.debaters[
        2
    ].temperature = 0.1  # debater_3 was not screened, but the file is pinned whole
    assert "agents_fingerprint was" in screened.refusal(changed)
    swapped = screened.agents.model_copy(deep=True)
    swapped.debaters[1].model = "openai/gpt-oss-120b"
    text = screened.refusal(swapped)
    assert "debater_2: no screen manifest" in text  # a new model is a new, unscreened folder


def test_a_different_extractor_is_refused(screened, monkeypatch):
    monkeypatch.setattr(holdout, "extractor_fingerprint", lambda: "changed-extractor")
    assert "extractor was" in screened.refusal()


def test_every_problem_is_listed_not_just_the_first(screened, tmp_path):
    edit_manifest(tmp_path, FLOOR, extractor="x")
    edit_manifest(tmp_path, GPT, prompt_suffix_sha256="y")
    text = screened.refusal()
    assert (
        "debater_1: screen extractor" in text and "debater_2: screen prompt_suffix_sha256" in text
    )


def test_a_screen_that_missed_its_target_is_refused_unless_accepted(tmp_path, settings, world):
    do_screen(tmp_path, settings, world, too_hard)  # 0% accuracy
    g = Guard(tmp_path, world)
    text = g.refusal()
    assert "the screen missed its target" in text and "below 40%" in text
    pin = g(accept_missed=True)
    assert pin["accepted_missed"] and not pin["agents"]["debater_1"]["target_met"]


def test_a_rescreen_under_another_run_name_and_seed_is_checked_by_name(tmp_path, settings, world):
    do_screen(tmp_path, settings, world)
    assert "no screen results" in Guard(tmp_path, world).refusal(screen_run="mmlupro-screen-s43")


def test_the_cli_check_prints_the_verdict(screened, tmp_path):
    out: list[str] = []
    code = holdout_main(
        ["check", "--config", str(CONFIG)],
        results_dir=tmp_path / "results",
        data_dir=screened.data_dir,
        out=out.append,
    )
    assert code == 0 and "finished and matches" in out[0]
    (screen_manifest(tmp_path, FLOOR)).unlink()
    out.clear()
    code = holdout_main(
        ["check", "--config", str(CONFIG)],
        results_dir=tmp_path / "results",
        data_dir=screened.data_dir,
        out=out.append,
    )
    assert code == 1 and "will not start" in out[0]


# --- wired into eval.run ---


class HoldoutRun:
    def __init__(self, tmp_path, settings, data_dir, behave=on_target):
        self.tmp_path, self.settings, self.data_dir = tmp_path, settings, data_dir
        self.factory = factory(behave)
        self.out: list[str] = []

    def __call__(self, *argv):
        return run_main(
            ["--dataset", "mmlupro-holdout", "--config", str(CONFIG), "--yes", *argv],
            provider_factory=self.factory,
            dataset=MMLUProHoldout(self.data_dir, selection_path("holdout", 2026, self.data_dir)),
            settings=self.settings,
            sleep=no_sleep,
            today=lambda: "2026-01-01",
            results_dir=self.tmp_path / "results",
            cache_dir=self.tmp_path / "cache",
            data_dir=self.data_dir,
            out=self.out.append,
        )

    @property
    def text(self):
        return "\n".join(self.out)

    def sent_nothing(self):
        made = getattr(self.factory, "made", {})
        return all(not p.calls for p in made.values())


def test_the_holdout_run_refuses_to_start_without_a_screen(tmp_path, settings, world):
    run = HoldoutRun(tmp_path, settings, world)
    assert run("--n", "2", "--sleep-between-s", "1") == 1
    assert "the holdout will not start" in run.text and "no screen results" in run.text
    assert run.sent_nothing()
    assert not (tmp_path / "results" / "mmlupro-holdout-s42").exists()


def test_force_does_not_bypass_the_guard(tmp_path, settings, world):
    run = HoldoutRun(tmp_path, settings, world)
    assert run("--n", "2", "--force") == 1 and run.sent_nothing()


def test_a_mismatch_refuses_before_any_call(screened, tmp_path, settings, world):
    edit_manifest(tmp_path, GPT, extractor="stale")
    run = HoldoutRun(tmp_path, settings, world)
    assert run("--n", "2", "--sleep-between-s", "1") == 1
    assert "debater_2: screen extractor was" in run.text and run.sent_nothing()


def test_a_dry_run_reports_the_refusal_but_still_estimates(tmp_path, settings, world):
    run = HoldoutRun(tmp_path, settings, world)
    assert run("--n", "2", "--dry-run") == 0
    assert "a real run would be refused" in run.text and "Dry run: nothing was sent." in run.text
    assert run.sent_nothing()


def test_a_matching_screen_lets_the_holdout_run_and_the_manifest_keeps_the_pin(
    screened, tmp_path, settings, world
):
    run = HoldoutRun(tmp_path, settings, world)
    assert run("--n", "2", "--sleep-between-s", "1") == 0, run.text
    assert "Holdout guard: screen 'mmlupro-screen-s42' is finished and matches." in run.text
    root = tmp_path / "results" / "mmlupro-holdout-s42"
    manifest = json.loads((root / "manifest.json").read_text("utf-8"))
    assert manifest["screen_pin"]["agents"]["debater_2"]["n"] == 60
    assert manifest["config"]["dataset"] == "mmlupro-holdout"
    records = [json.loads(p.read_text("utf-8")) for p in (root / "questions").glob("*.json")]
    assert len(records) == 2
    assert set(records[0]["conditions"]) == {"A1", "A2", "A3", "B", "D"}  # no C, no D-vote


def test_the_holdout_run_is_resumable_and_rechecks_the_guard(screened, tmp_path, settings, world):
    first = HoldoutRun(tmp_path, settings, world)
    assert first("--n", "1", "--sleep-between-s", "1") == 0
    edit_manifest(tmp_path, FLOOR, agents_fingerprint="changed-since")
    again = HoldoutRun(tmp_path, settings, world)
    assert again("--n", "2", "--sleep-between-s", "1") == 1 and again.sent_nothing()


def test_other_datasets_do_not_need_a_screen(tmp_path, settings, world):
    run = HoldoutRun(tmp_path, settings, world)
    out: list[str] = []
    code = run_main(
        ["--dataset", "mmlupro-screen", "--config", str(CONFIG), "--n", "1", "--dry-run"],
        provider_factory=run.factory,
        dataset=MMLUProScreen(world, selection_path("screen", 42, world)),
        settings=settings,
        sleep=no_sleep,
        results_dir=tmp_path / "results",
        cache_dir=tmp_path / "cache",
        data_dir=world,
        out=out.append,
    )
    assert code == 0 and "Holdout guard" not in "\n".join(out)
