"""MATH-500 levels 4-5 dataset, run profile, LaTeX safety and cut-off detection. Offline."""

import io
import json

import pytest

from app.core.settings import BACKEND_DIR, load_agents
from app.db.session import init_db, make_engine
from app.providers.base import ProviderError
from app.providers.cached import CachedProvider
from eval import report
from eval.datasets import (
    MATH45,
    MATH500_URL,
    DatasetError,
    get_dataset,
    load_order,
    order_path,
)
from eval.datasets import main as datasets_main
from eval.report import build_report, splice_readme
from eval.run import apply_profile, main, parse_rpm
from eval.runner import classify_error
from eval.tests.helpers import (
    LATEX,
    eligible_math_indices,
    gold_of,
    math_rows,
    write_math,
)
from eval.tests.test_run import Env


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def raw(rows) -> bytes:
    return ("\n".join(json.dumps(r) for r in rows) + "\n").encode()


# --- fetch ---


def test_fetch_uses_the_media_url_and_stores_the_file(tmp_path):
    urls = []

    def opener(url, timeout):
        urls.append(url)
        return Resp(raw(math_rows()))

    ds = MATH45(tmp_path / "d" / "m.jsonl")
    assert ds.fetch(opener) == 500
    assert urls == [MATH500_URL]
    assert MATH500_URL.startswith("https://media.githubusercontent.com/media/openai/prm800k/")
    assert len(ds.source_sha256()) == 64


def test_a_git_lfs_pointer_is_refused_with_a_clear_error_and_nothing_is_written(tmp_path):
    pointer = (
        b"version https://git-lfs.github.com/spec/v1\noid sha256:" + b"0" * 64 + b"\nsize 446098\n"
    )
    ds = MATH45(tmp_path / "m.jsonl")
    with pytest.raises(DatasetError, match="git-lfs pointer.*media.githubusercontent.com"):
        ds.fetch(lambda url, timeout: Resp(pointer))
    assert not ds.path.exists()


BAD_DOWNLOADS = {
    "html": (lambda: b"<html>not data</html>", "not MATH-500 jsonl"),
    "wrong_fields": (lambda: raw([{"question": "q", "answer": "1"}] * 500), "missing fields"),
    "partial": (lambda: raw(math_rows(n=499)), "expected 500 rows, got 499"),
    "not_utf8": (lambda: bytes([0xFF, 0xFE]) + b"bad", "not MATH-500 jsonl"),
}


@pytest.mark.parametrize("case", list(BAD_DOWNLOADS))
def test_other_bad_downloads_are_refused(tmp_path, case):
    make_body, message = BAD_DOWNLOADS[case]
    ds = MATH45(tmp_path / "m.jsonl")
    with pytest.raises(DatasetError, match=message):
        ds.fetch(lambda url, timeout: Resp(make_body()))
    assert not ds.path.exists()


def test_missing_file_says_how_to_fetch(tmp_path):
    with pytest.raises(DatasetError, match="fetch --dataset math45"):
        MATH45(tmp_path / "nope.jsonl").load()


# --- subset ---


def test_subset_is_level_4_and_5_with_plain_integer_answers_only(tmp_path):
    overrides = {
        4: {"answer": "1,018"},  # thousands commas: kept
        8: {"answer": "-5"},  # negative: kept
        9: {"answer": "3.5"},  # decimal: dropped
        13: {"answer": "1,00"},  # bad grouping: dropped
        14: {"answer": "+5"},  # plus sign: dropped
        18: {"answer": "x^2"},  # text: dropped
        23: {"answer": "12", "level": "5"},  # level given as a string: kept
        24: {"answer": "12", "level": 3},  # level 3: dropped
        28: {"answer": "12", "level": 6},  # not a level: dropped
    }
    ds = write_math(tmp_path / "m.jsonl", overrides)
    got = [int(q.qid.split("-")[1]) for q in ds.load()]
    assert got == eligible_math_indices(math_rows(overrides))  # source order, by the same rule
    by_id = {q.qid: q for q in ds.load()}
    assert ds.gold_label(by_id["math500-4"]) == "1018"
    assert ds.gold_label(by_id["math500-8"]) == "-5"
    for dropped in (9, 13, 14, 18, 24, 28):
        assert f"math500-{dropped}" not in by_id
    assert "math500-23" in by_id and by_id["math500-23"].meta["level"] == 5


def test_counts_by_level_are_printed_when_sampling(tmp_path, capsys, monkeypatch):
    ds = write_math(tmp_path / "m.jsonl")
    rows = math_rows()
    ok = eligible_math_indices(rows)
    lv4 = sum(rows[i]["level"] == 4 for i in ok)
    lv5 = sum(rows[i]["level"] == 5 for i in ok)
    assert len(ok) == lv4 + lv5 and lv4 > 0 and lv5 > 0
    assert ds.describe(ds.load()) == (
        f"{len(ok)} eligible questions (level 4: {lv4}, level 5: {lv5}; "
        "integer answers only) out of the 500 in MATH-500"
    )
    monkeypatch.setattr("eval.datasets.DATASETS", {"math45": lambda: MATH45(tmp_path / "m.jsonl")})
    assert datasets_main(["sample", "--dataset", "math45", "--seed", "42"], data_dir=tmp_path) == 0
    out = capsys.readouterr().out
    assert f"{len(ok)} eligible questions (level 4: {lv4}, level 5: {lv5}" in out
    assert (tmp_path / "math45_ids_seed42.json").exists()


def test_order_is_seeded_stored_per_dataset_and_prefix_stable(tmp_path):
    ds = write_math(tmp_path / "m.jsonl")
    order = load_order(ds, 42, tmp_path)
    assert sorted(order) == sorted(q.qid for q in ds.load())
    assert order_path("math45", 42, tmp_path).name == "math45_ids_seed42.json"
    assert load_order(ds, 42, tmp_path) == order
    assert load_order(ds, 42, tmp_path)[:25] == order[:25]  # a pilot is a prefix
    assert load_order(ds, 7, tmp_path) != order


def test_registry_and_defaults():
    assert isinstance(get_dataset("math45"), MATH45)
    ds = get_dataset("math45")
    assert ds.prompt_suffix == "Give the final answer as a plain integer with no units."
    assert ds.profile.max_tokens == 4096 and ds.profile.rpm == {"groq": 2}
    assert ds.profile.sleep_s == 120 and ds.profile.repair_factor > 1
    assert get_dataset("gsm8k").profile.is_default  # GSM8K runs exactly as before


def test_scoring_is_exact_by_value_without_fuzzy_matching(tmp_path):
    ds = write_math(tmp_path / "m.jsonl", {4: {"answer": "1,018"}, 8: {"answer": "-5"}})
    q = {x.qid: x for x in ds.load()}
    assert ds.score(q["math500-4"], "1018").correct
    assert ds.score(q["math500-4"], "$1,018").correct
    assert ds.score(q["math500-4"], "1018.0").correct
    assert ds.score(q["math500-8"], "-5").correct
    assert ds.score(q["math500-8"], "5").status == "wrong"
    assert ds.score(q["math500-8"], "-5 degrees").status == "non_numeric"
    assert ds.score(q["math500-8"], r"\boxed{-5}").status == "non_numeric"
    assert ds.score(q["math500-8"], None).status == "missing"


# --- LaTeX ---


def test_the_prompt_is_the_problem_text_unchanged_plus_the_suffix(tmp_path):
    ds = write_math(tmp_path / "m.jsonl")
    q = ds.load()[0]
    assert q.text.endswith("Find the value.") and LATEX in q.text
    assert ds.prompt(q) == q.text + "\n\n" + ds.prompt_suffix


class MathEnv(Env):
    def __init__(self, tmp_path, settings, behave=None, **kw):
        super().__init__(tmp_path, settings, behave or (lambda c: str(gold_of(c.q))), **kw)
        self.dataset = write_math(tmp_path / "math.jsonl", kw.get("overrides"))

    @property
    def run_dir(self):
        return self.tmp_path / "results" / "math45-s42"


def pin_math(env, ids):
    sha = env.dataset.source_sha256()
    all_ids = [q.qid for q in env.dataset.load()]
    first = [f"math500-{i}" for i in ids]
    order = first + [q for q in all_ids if q not in first]
    (env.tmp_path / "data").mkdir(exist_ok=True)
    order_path("math45", 42, env.tmp_path / "data").write_text(
        json.dumps({"dataset": "math45", "seed": 42, "source_sha256": sha, "order": order}),
        encoding="utf-8",
    )


def test_latex_reaches_every_prompt_verbatim_and_scoring_still_works(tmp_path, settings):
    env = MathEnv(tmp_path, settings)
    pin_math(env, [4, 8])
    assert env.run("--dataset", "math45", "--n", "2") == 0
    for agent in ("debater_1", "judge"):
        calls = env.calls(agent)
        assert calls
        for c in calls:
            assert LATEX in c.text  # unchanged: $, {}, \, \\, \n all intact
            assert "Give the final answer as a plain integer with no units." in c.text
    recs = env.records()
    assert sorted(recs) == ["math500-4", "math500-8"]
    assert all(r["conditions"][k]["correct"] for r in recs.values() for k in ("A1", "B", "C", "D"))
    assert recs["math500-4"]["question"].count("\\") == LATEX.count("\\")  # stored as written
    assert recs["math500-4"]["meta"]["level"] in (4, 5)


def test_latex_survives_the_response_cache_round_trip(tmp_path, settings):
    engine = make_engine(f"sqlite:///{(tmp_path / 'c.db').as_posix()}")
    init_db(engine)
    env = MathEnv(tmp_path, settings)

    def cached(agents):
        return {k: CachedProvider(v, engine) for k, v in env.factory(agents).items()}

    pin_math(env, [4])
    env.run("--dataset", "math45", "--n", "1", provider_factory=cached)
    sent = sum(len(env.calls(a)) for a in ("debater_1", "debater_2", "debater_3", "judge"))
    assert sent > 0
    # same question under a new run name: every request replays from the cache
    env.run("--dataset", "math45", "--n", "1", "--run", "again", provider_factory=cached)
    second = sum(len(env.calls(a)) for a in ("debater_1", "debater_2", "debater_3", "judge"))
    assert second == 0
    first = json.loads((env.run_dir / "questions" / "math500-4.json").read_text("utf-8"))
    again = json.loads(
        (env.tmp_path / "results" / "again" / "questions" / "math500-4.json").read_text("utf-8")
    )
    assert first["conditions"]["D"]["answer"] == again["conditions"]["D"]["answer"]


def test_a_reply_with_an_invalid_json_escape_is_a_stored_missing_answer(tmp_path, settings):
    def behave(c):
        if c.agent_id == "debater_2" and c.role == "debater":
            return 'RAW:{"reasoning": "so \\(x\\) is 3", "final_answer": "12", "confidence": 80}'
        return str(gold_of(c.q))

    env = MathEnv(tmp_path, settings, behave)
    pin_math(env, [4])
    assert env.run("--dataset", "math45", "--n", "1") == 0
    c = env.records()["math500-4"]["conditions"]
    assert c["A2"]["status"] == "missing" and not c["A2"]["truncated"]
    assert c["B"]["correct"]  # the two valid votes carry the majority


# --- run folder, manifest, profile ---


def test_math_runs_in_their_own_folder_and_never_mix_with_gsm8k(tmp_path, settings):
    env = MathEnv(tmp_path, settings)
    pin_math(env, [4])
    env.run("--dataset", "math45", "--n", "1")
    gsm = Env(tmp_path, settings)
    from eval.tests.test_run import pin_order

    pin_order(gsm, [1])
    assert gsm.run("--n", "1") == 0  # the gsm8k dataset object, default run name
    assert (tmp_path / "results" / "math45-s42").is_dir()
    assert (tmp_path / "results" / "gsm8k-s42").is_dir()
    assert not any(p.stem.startswith("gsm8k") for p in env.run_dir.rglob("*.json"))
    manifest = json.loads((env.run_dir / "manifest.json").read_text("utf-8"))
    assert manifest["config"]["dataset"] == "math45"
    assert manifest["config"]["profile"] == {"max_tokens": 4096}  # mock config has no groq
    gsm_manifest = json.loads((tmp_path / "results" / "gsm8k-s42" / "manifest.json").read_text())
    assert "profile" not in gsm_manifest["config"]  # gsm8k runs resume exactly as before


def test_profile_changes_only_the_eval_copy_never_agents_yaml():
    agents = load_agents(BACKEND_DIR / "config" / "agents.yaml")
    before = agents.model_dump_json()
    ds = get_dataset("math45")
    copy, applied = apply_profile(agents, ds.profile, None, {})
    assert agents.model_dump_json() == before  # the app's config object is untouched
    assert all(a.max_tokens == 1536 for a in agents.all_agents())
    assert all(a.max_tokens == 4096 for a in copy.all_agents())
    assert copy.providers["groq"].rpm == 2 and agents.providers["groq"].rpm is None
    assert applied == {"max_tokens": 4096, "rpm": {"groq": 2}}
    yaml_text = (BACKEND_DIR / "config" / "agents.yaml").read_text(encoding="utf-8")
    assert "max_tokens: 1536" in yaml_text and "4096" not in yaml_text


def test_profile_overrides_never_lower_a_limit_and_zero_means_off():
    agents = load_agents(BACKEND_DIR / "config" / "agents.yaml")
    ds = get_dataset("math45")
    big, _ = apply_profile(agents, ds.profile, 8000, {})
    assert all(a.max_tokens == 8000 for a in big.all_agents())
    agents.judge.max_tokens = 9000
    kept, _ = apply_profile(agents, ds.profile, 4096, {})
    assert kept.judge.max_tokens == 9000  # never lowered
    off, applied = apply_profile(agents, ds.profile, 0, {"groq": 0})
    assert all(a.max_tokens == 1536 or a.id == "judge" for a in off.all_agents())
    assert off.providers["groq"].rpm is None and "max_tokens" not in applied
    plain, none = apply_profile(agents, get_dataset("gsm8k").profile, None, {})
    assert none == {} and plain.model_dump_json() == agents.model_dump_json()


def test_parse_rpm():
    assert parse_rpm("groq=2, gemini=0.5") == {"groq": 2.0, "gemini": 0.5}
    assert parse_rpm("") == {}
    for bad in ("groq", "groq=x", "=2", "groq=-1"):
        with pytest.raises(ValueError):
            parse_rpm(bad)


def run_dry(env, *argv):
    out: list[str] = []
    code = main(
        ["--n", "3", "--dry-run", *argv],
        dataset=env.dataset,
        settings=env.settings,
        results_dir=env.tmp_path / "results",
        data_dir=env.tmp_path / "data",
        out=out.append,
    )
    assert code == 0
    return "\n".join(out)


def test_dry_run_for_math45_shows_the_longer_pause_pacing_and_repair_allowance(tmp_path, settings):
    env = MathEnv(tmp_path, settings)
    pin_math(env, [4, 8, 9])
    text = run_dry(env, "--dataset", "math45", "--config", str(BACKEND_DIR / "config/agents.yaml"))
    assert "120s each" in text and "about 6 min total" in text
    assert "1.3x for repair calls" in text
    assert "Eval-only output limit: 4096 tokens" in text and "agents.yaml is unchanged" in text
    assert "groq paced at 2 request(s)/min: at least 30s between calls" in text
    assert "Dry run: nothing was sent." in text
    assert not (env.run_dir / "manifest.json").exists()


def test_dry_run_for_gsm8k_is_unchanged(tmp_path, settings):
    env = Env(tmp_path, settings)
    from eval.tests.test_run import pin_order

    pin_order(env, [0, 1, 2])
    text = run_dry(env, "--config", str(BACKEND_DIR / "config/agents.yaml"))
    assert "60s each" in text and "repair calls" in text and "no repair calls" in text
    assert "Eval-only" not in text and "paced at" not in text


def test_sleep_flag_overrides_the_dataset_default(tmp_path, settings):
    for sub, flag, expected in (("a", ["--sleep-between-s", "7"], 7.0), ("b", [], 120.0)):
        folder = tmp_path / sub
        folder.mkdir()
        env = MathEnv(folder, settings)
        pin_math(env, [4, 8])
        env.run("--dataset", "math45", "--n", "2", *flag, dataset_sleep=True)
        assert env.sleeps == [expected]  # one pause, between the two questions
    gsm_folder = tmp_path / "c"
    gsm_folder.mkdir()
    from eval.tests.test_run import pin_order

    gsm = Env(gsm_folder, settings)
    pin_order(gsm, [1, 2])
    gsm.run("--n", "2", dataset_sleep=True)
    assert gsm.sleeps == [60.0]  # GSM8K keeps its old default


# --- cut-off detection ---


@pytest.mark.parametrize(
    "message,kind",
    [
        ("empty_response (finish_reason=length)", "model"),
        ("empty_response (finish_reason=stop)", "transient"),
        ("rate_limited (HTTP 429)", "quota"),
    ],
)
def test_a_length_stop_is_the_models_failure_not_an_outage(message, kind):
    assert classify_error(message) == kind


def run_truncation(tmp_path, settings, behave):
    env = MathEnv(tmp_path, settings, behave)
    pin_math(env, [4])
    assert env.run("--dataset", "math45", "--n", "1") == 0
    return env, env.records()["math500-4"]


def test_empty_reply_stopped_on_the_limit_is_stored_and_counted_as_cut_off(tmp_path, settings):
    def behave(c):
        if c.agent_id == "debater_2" and c.role == "debater" and c.round == 0:
            return ProviderError("empty_response (finish_reason=length)", category="empty_response")
        return str(gold_of(c.q))

    env, rec = run_truncation(tmp_path, settings, behave)
    c = rec["conditions"]
    assert c["A2"]["status"] == "missing" and c["A2"]["truncated"] and not c["A2"]["correct"]
    assert not c["A1"]["truncated"] and c["B"]["correct"]
    assert rec["facts"]["truncated_turns"] >= 1
    assert not (env.run_dir / "skipped.json").exists()  # hard problems are not skipped as errors
    assert sum(1 for x in env.calls("debater_2") if x.round == 0) == 1  # and not retried 3 times


def test_json_cut_off_mid_way_counts_as_cut_off_but_prose_and_bad_schema_do_not(tmp_path, settings):
    cut = '{"reasoning": "Step 1: \\\\frac{1}{2} of the total is {"'

    def behave(c):
        if c.role == "debater" and c.round == 0:
            return {
                "debater_1": "RAW:" + cut,
                "debater_2": "RAW:I think it is eleven.",
                "debater_3": 'RAW:{"unexpected": 1}',
            }[c.agent_id]
        return str(gold_of(c.q))

    _, rec = run_truncation(tmp_path, settings, behave)
    c = rec["conditions"]
    assert c["A1"]["truncated"] and c["A1"]["status"] == "missing"
    assert not c["A2"]["truncated"] and not c["A3"]["truncated"]
    assert all(c[k]["status"] == "missing" for k in ("A1", "A2", "A3"))
    assert c["B"]["note"] == "no_valid_answers" and not c["B"]["correct"]


def test_a_judge_cut_off_by_the_limit_is_flagged_on_c_and_d(tmp_path, settings):
    def behave(c):
        if c.role == "judge":
            return ProviderError("empty_response (finish_reason=length)", category="empty_response")
        return str(gold_of(c.q))

    _, rec = run_truncation(tmp_path, settings, behave)
    c = rec["conditions"]
    assert c["D"]["note"] == "judge_failed" and c["D"]["truncated"] and c["C"]["truncated"]
    assert not c["B"]["truncated"]
    assert rec["facts"]["truncated_turns"] >= 1


# --- report ---


def synthetic(i, **over):
    names = ["A1", "A2", "A3", "B", "C", "D", "D_vote"]
    conds = {
        n: {
            "answer": "12",
            "status": "correct",
            "correct": True,
            "fallback": False,
            "note": None,
            "cost": {"calls": 1, "api_calls": 1, "tokens": 10, "latency_ms": 100, "cache_hits": 0},
        }
        for n in names
    }
    rec = {
        "qid": f"math500-{i}",
        "gold": "12",
        "finished_at": "2026-10-19T10:00:00+00:00",
        "facts": {
            "rounds_run": 1,
            "early_stopped": True,
            "c_equals_d": True,
            "prefix_consistent": True,
            "cache_hits_d": 0,
            "truncated_turns": 0,
        },
        "conditions": conds,
        "turns": [],
    }
    for k, v in over.items():
        rec["conditions"][k].update(v)
    return rec


MATH_MANIFEST = {
    "config": {
        "dataset": "math45",
        "seed": 42,
        "prompt_suffix": "Give the final answer as a plain integer with no units.",
        "agents_fingerprint": "f00",
        "profile": {"max_tokens": 4096, "rpm": {"groq": 2}},
    }
}


def test_report_labels_the_dataset_and_the_eval_only_settings():
    text = build_report([synthetic(0)], MATH_MANIFEST)
    assert "MATH-500 test split, levels 4-5, integer answers only" in text
    assert "Eval-only settings: output limit 4096 tokens per answer, groq paced at 2" in text
    assert "Give the final answer as a plain integer with no units." in text
    gsm = build_report([synthetic(0)], {"config": {**MATH_MANIFEST["config"], "dataset": "gsm8k"}})
    assert "GSM8K (test split)" in gsm and "MATH-500" not in gsm.split("#### Limitations")[0]


def test_math_limitations_cover_contamination_subset_and_the_integer_filter():
    text = build_report([synthetic(0)], MATH_MANIFEST)
    lim = text.split("#### Limitations")[1]
    assert "very likely in the training data" in lim and "contamination" in lim
    assert "Small subset" in lim and "Small sample" in lim
    assert "Integer-only filter" in lim and "easier than the full benchmark" in lim
    assert "Cut-off outputs" in lim and "raised to 4096 tokens" in lim
    assert "Free-tier models change" in lim and "Fallback models" in lim
    gsm = build_report([synthetic(0)], {"config": {**MATH_MANIFEST["config"], "dataset": "gsm8k"}})
    glim = gsm.split("#### Limitations")[1]
    assert "Integer-only filter" not in glim and "GSM8K is public" in glim


def test_cut_off_is_a_visible_column_and_summary_line():
    recs = [
        synthetic(0, A2={"correct": False, "status": "missing", "answer": None, "truncated": True})
    ]
    recs[0]["facts"]["truncated_turns"] = 2
    text = build_report(recs, MATH_MANIFEST)
    header = next(ln for ln in text.splitlines() if ln.startswith("| Condition | Non-numeric"))
    assert "Cut off" in header
    row = next(ln for ln in text.splitlines() if ln.startswith("| A2 |"))
    assert [c.strip() for c in row.strip("|").split("|")][1:4] == ["0", "1", "1"]
    assert (
        "cut off by the token limit (debater turns plus judge calls): 2 across 1 questions" in text
    )


def test_older_records_without_the_new_fields_still_report():
    rec = synthetic(0)
    del rec["facts"]["truncated_turns"]
    text = build_report([rec], {"config": {"dataset": "gsm8k", "seed": 42}})
    assert "across 1 questions" in text and "Cut off" in text


def test_backslashes_and_dollars_in_answers_and_readme_are_not_interpreted(tmp_path):
    rec = synthetic(0, B={"answer": r"\1 $1 \g<0> \\ $$ {x}", "correct": False, "status": "wrong"})
    rec["conditions"]["D"].update(correct=True)
    text = build_report([rec], MATH_MANIFEST)
    assert r"`\1 $1 \g<0> \\ $$ {x}`" in text  # shown as written in the fixed/broke table
    readme = f"top \\1\n{report.START_MARKER}\nold\n{report.END_MARKER}\nbottom $1 \\g<0>\n"
    out = splice_readme(readme, text)
    assert out.startswith("top \\1\n") and out.endswith("bottom $1 \\g<0>\n")
    assert r"\1 $1 \g<0>" in out
