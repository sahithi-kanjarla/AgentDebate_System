"""Report tests on synthetic result files in a temp folder. Nothing here reads eval/results."""

import json
from pathlib import Path

import pytest

from eval import report
from eval.report import END_MARKER, START_MARKER, build_report, main, splice_readme
from eval.store import ResultStore

NAMES = ["A1", "A2", "A3", "B", "C", "D", "D_vote"]


def condition(correct, answer=None, fallback=False, status=None, note=None, api=5):
    return {
        "answer": answer if answer is not None else ("10" if correct else "7"),
        "status": status or ("correct" if correct else "wrong"),
        "correct": correct,
        "fallback": fallback,
        "note": note,
        "cost": {
            "calls": api,
            "api_calls": api,
            "tokens": 100,
            "latency_ms": 2000,
            "cache_hits": 0,
        },
    }


def record(qid, outcomes, gold="10", **over):
    """outcomes: dict condition -> bool; unlisted conditions use outcomes.get('all', True)."""
    default = outcomes.get("all", True)
    conds = {n: condition(outcomes.get(n, default)) for n in NAMES}
    for k, v in over.items():
        conds[k].update(v)
    return {
        "qid": qid,
        "question": "q",
        "gold": gold,
        "finished_at": "2026-10-19T10:00:00+00:00",
        "facts": {
            "rounds_run": 2,
            "early_stopped": True,
            "c_equals_d": False,
            "prefix_consistent": True,
            "cache_hits_d": 0,
        },
        "conditions": conds,
        "turns": [
            {"label": f"Debater {i}", "provider": "prov", "model": f"m{i}", "fallback_used": False}
            for i in (1, 2, 3)
        ],
        "judge_d": {"fallback_used": False},
        "judge_c": None,
    }


MANIFEST = {
    "config": {
        "dataset": "gsm8k",
        "seed": 42,
        "prompt_suffix": "Give the final answer as a plain number with no units.",
        "agents_fingerprint": "abc123",
        "allow_fallback": False,
        "early_stop": True,
    }
}


def test_tiny_n_all_correct_says_no_detectable_difference_and_flags_everything():
    recs = [record(f"q{i}", {}) for i in range(3)]
    text = build_report(recs, MANIFEST)
    assert "no detectable difference" in text
    assert "Every condition scored 100%" in text
    assert "Ceiling effect" in text
    assert "Very small sample (n = 3)" in text
    assert "Point estimates are not ranked" in text
    assert "outperform" not in text and "better than" not in text


def test_tiny_n_with_a_difference_that_is_not_supported_is_not_ranked():
    recs = [
        record("q0", {"all": True, "B": False}),  # debate fixed it
        record("q1", {}),
        record("q2", {}),
    ]
    text = build_report(recs, MANIFEST)
    primary = next(line for line in text.splitlines() if line.startswith("**Primary"))
    assert "no detectable difference" in primary and "higher" not in primary
    assert "p = 1.000" in text or "p = 0.5" in text
    assert "Every condition scored 100%" not in text


def test_ceiling_note_appears_only_when_every_condition_is_at_least_95_percent():
    ok = [record(f"q{i}", {}) for i in range(100)]
    ok[0] = record("q0", {"B": False})  # B at 99%, rest 100%
    assert "cannot be detected on this dataset at this sample size" in build_report(ok, MANIFEST)
    low = [record(f"q{i}", {}) for i in range(100)]
    for i in range(10):  # D at 90%
        low[i] = record(f"q{i}", {"D": False})
    assert "Ceiling effect" not in build_report(low, MANIFEST)


def test_a_clear_difference_is_reported_as_one():
    recs = [record(f"q{i}", {"all": True, "B": i >= 25}) for i in range(100)]
    text = build_report(recs, MANIFEST)
    primary = next(line for line in text.splitlines() if line.startswith("**Primary"))
    assert "D higher than B" in primary


def test_fixed_and_broke_lists_ids_gold_and_every_answer():
    recs = [
        record(
            "q-fixed",
            {"B": False, "A1": False},
            gold="42",
        ),
        record("q-broke", {"D": False, "C": False}, gold="8"),
        record("q-same", {}),
    ]
    recs[0]["conditions"]["B"]["answer"] = "41"
    recs[0]["conditions"]["D"]["answer"] = "42"
    recs[1]["conditions"]["D"]["answer"] = "9"
    text = build_report(recs, MANIFEST)
    fixed = text.split("Debate fixed: majority vote (B) wrong, debate (D) right")[1]
    fixed = fixed.split("Debate broke")[0]
    assert "`q-fixed`" in fixed and "`42`" in fixed and "`41`" in fixed
    assert "q-broke" not in fixed and "q-same" not in fixed
    broke = text.split("Debate broke: majority vote (B) right, debate (D) wrong")[1].split("####")[
        0
    ]
    assert "`q-broke`" in broke and "`8`" in broke and "`9`" in broke
    assert "**Debate fixed: majority vote (B) wrong, debate (D) right (1):**" in text


def test_fixed_broke_empty_says_none():
    text = build_report([record("q0", {})], MANIFEST)
    assert "majority vote (B) wrong, debate (D) right: none." in text
    assert "majority vote (B) right, debate (D) wrong: none." in text


def test_primary_only_numbers_sit_beside_the_all_answers_numbers():
    recs = [record(f"q{i}", {}) for i in range(4)]
    recs[0]["conditions"]["A1"]["fallback"] = True
    recs[0]["conditions"]["A1"].update(correct=False, status="wrong")
    text = build_report(recs, MANIFEST)
    line = next(ln for ln in text.splitlines() if ln.startswith("| A1 single model"))
    cells = [c.strip() for c in line.strip("|").split("|")]
    assert cells[1] == "3/4" and cells[3] == "3/3"  # all answers vs without the fallback one
    assert cells[5].startswith("1 (25.0%)")


def test_non_numeric_and_missing_counts():
    recs = [record("q0", {}), record("q1", {})]
    recs[0]["conditions"]["A2"].update(correct=False, status="non_numeric", answer="10 dollars")
    recs[1]["conditions"]["A2"].update(correct=False, status="missing", answer=None)
    text = build_report(recs, MANIFEST)
    line = next(ln for ln in text.splitlines() if ln.startswith("| A2 |"))
    assert [c.strip() for c in line.strip("|").split("|")][1:3] == ["1", "1"]


def test_limitations_and_disclosure_are_in_the_report():
    text = build_report([record("q0", {})], MANIFEST)
    for needle in (
        "Training-data contamination",
        "Small sample",
        "Free-tier models change",
        "Fallback models",
        "Give the final answer as a plain number with no units.",
        "Judge asymmetry",
        "abc123",
    ):
        assert needle in text


def test_empty_results():
    assert "nothing to report" in build_report([], None)


# --- command line and README ---


def make_run(tmp_path: Path, recs) -> Path:
    results = tmp_path / "results"
    store = ResultStore(results / "gsm8k-s42")
    for r in recs:
        store.save_question(r)
    store.write_manifest(MANIFEST)
    return results


def snapshot(folder: Path):
    return {str(p.relative_to(folder)): p.read_bytes() for p in folder.rglob("*") if p.is_file()}


README = f"# T\n\nintro\n\n{START_MARKER}\nOLD\n{END_MARKER}\n\noutro\n"


def test_default_prints_only_and_leaves_readme_and_results_untouched(tmp_path):
    results = make_run(tmp_path, [record(f"q{i}", {}) for i in range(3)])
    readme = tmp_path / "README.md"
    readme.write_text(README, encoding="utf-8")
    before = snapshot(results)
    out: list[str] = []
    assert main([], results_dir=results, readme=readme, out=out.append) == 0
    assert "#### Accuracy" in out[0]
    assert readme.read_text(encoding="utf-8") == README
    assert snapshot(results) == before  # read-only on the results folder


def test_write_readme_rewrites_only_between_the_markers_and_is_idempotent(tmp_path):
    results = make_run(tmp_path, [record(f"q{i}", {}) for i in range(3)])
    readme = tmp_path / "README.md"
    readme.write_text(README, encoding="utf-8")
    before = snapshot(results)
    assert main(["--write-readme"], results_dir=results, readme=readme, out=lambda t: None) == 0
    first = readme.read_text(encoding="utf-8")
    head, rest = first.split(START_MARKER)
    body, tail = rest.split(END_MARKER)
    assert head == "# T\n\nintro\n\n" and tail == "\n\noutro\n"
    assert "OLD" not in body and "#### Accuracy" in body
    assert main(["--write-readme"], results_dir=results, readme=readme, out=lambda t: None) == 0
    assert readme.read_text(encoding="utf-8") == first
    assert snapshot(results) == before


def test_write_readme_keeps_crlf_line_endings(tmp_path):
    results = make_run(tmp_path, [record("q0", {})])
    readme = tmp_path / "README.md"
    readme.write_bytes(README.replace("\n", "\r\n").encode())
    main(["--write-readme"], results_dir=results, readme=readme, out=lambda t: None)
    raw = readme.read_bytes()
    assert b"\n" not in raw.replace(b"\r\n", b"")


@pytest.mark.parametrize(
    "text",
    [
        "no markers here",
        f"{END_MARKER} {START_MARKER}",
        f"{START_MARKER} {START_MARKER} {END_MARKER}",
        f"{START_MARKER} only start",
    ],
)
def test_bad_markers_are_refused_and_the_file_is_untouched(tmp_path, text):
    with pytest.raises(ValueError):
        splice_readme(text, "x")
    results = make_run(tmp_path, [record("q0", {})])
    readme = tmp_path / "README.md"
    readme.write_text(text, encoding="utf-8")
    out: list[str] = []
    assert main(["--write-readme"], results_dir=results, readme=readme, out=out.append) == 1
    assert readme.read_text(encoding="utf-8") == text
    assert any(line.startswith("error:") for line in out)


def test_missing_run_and_empty_run(tmp_path):
    out: list[str] = []
    assert main([], results_dir=tmp_path, readme=tmp_path / "R.md", out=out.append) == 1
    results = make_run(tmp_path, [])
    readme = tmp_path / "R.md"
    readme.write_text(README, encoding="utf-8")
    out.clear()
    assert main(["--write-readme"], results_dir=results, readme=readme, out=out.append) == 1
    assert readme.read_text(encoding="utf-8") == README


def test_partial_files_from_a_running_pilot_are_ignored(tmp_path):
    results = make_run(tmp_path, [record("q0", {})])
    (results / "gsm8k-s42" / "questions" / "q1.json").write_text(
        '{"qid": "q1", "cond', encoding="utf-8"
    )
    out: list[str] = []
    assert main([], results_dir=results, readme=tmp_path / "R.md", out=out.append) == 0
    assert "1 finished question(s)" in out[0]


def test_report_is_deterministic():
    recs = [record(f"q{i}", {"B": i % 3 != 0}) for i in range(30)]
    assert build_report(recs, MANIFEST) == build_report(list(reversed(recs)), MANIFEST)


def test_report_module_has_no_network_or_provider_imports():
    src = Path(report.__file__).read_text(encoding="utf-8")
    assert "urllib" not in src and "httpx" not in src and "app.providers" not in src


def test_end_to_end_from_real_harness_output(tmp_path, settings):
    """Run the harness on scripted mock providers, then report on what it wrote."""
    from eval.tests.test_run import Env, pin_order

    env = Env(tmp_path, settings)
    pin_order(env, [0, 1, 2])
    assert env.run() == 0
    recs, manifest, skipped = report.load_run(env.run_dir)
    text = build_report(recs, manifest, skipped)
    assert "3 finished question(s)" in text
    fixed = text.split("Debate fixed: majority vote (B) wrong, debate (D) right")[1]
    assert "`gsm8k-test-0`" in fixed.split("Debate broke")[0]
    assert json.loads((env.run_dir / "manifest.json").read_text())["config"]["agents_fingerprint"]


def _letters(rec, a1, a2, a3, b_correct, d_correct):
    for key, ans in (("A1", a1), ("A2", a2), ("A3", a3)):
        rec["conditions"][key]["answer"] = ans
        rec["conditions"][key]["status"] = "missing" if ans is None else "wrong"
    rec["conditions"]["B"]["correct"] = b_correct
    rec["conditions"]["D"]["correct"] = d_correct
    return rec


def test_exploratory_section_splits_no_majority_and_wrong_majority_and_is_labelled():
    recs = [
        _letters(record("q0", {}), "A", "A", "B", True, True),  # majority right: excluded
        _letters(record("q1", {}), "A", "B", "C", False, True),  # no majority
        _letters(record("q2", {}), "A", None, "B", False, False),  # one vote each: no majority
        _letters(record("q3", {}), "C", "C", "D", False, True),  # majority wrong
        _letters(record("q4", {}), "C", "C", None, False, False),  # majority wrong
    ]
    text = report.exploratory_section(recs)
    rows = {
        ln.split("|")[1].strip(): [c.strip() for c in ln.strip("|").split("|")[1:]]
        for ln in text.splitlines()
        if ln.startswith("| ") and "Round-0" not in ln
    }
    no_majority = "No majority (fewer than 2 matching valid round-0 answers)"
    assert rows[no_majority] == ["2", "0/2", "1/2"]
    assert rows["Majority wrong"] == ["2", "0/2", "1/2"]
    assert rows["Either of the above"] == ["4", "0/4", "2/4"]
    assert "descriptive and post-hoc" in text
    assert "only pre-declared comparison" in text


def test_exploratory_section_is_not_added_to_a_numeric_dataset_report():
    text = build_report([record("q0", {})], MANIFEST)
    assert "Exploratory, descriptive and post-hoc" not in text


# --- exploratory debate dynamics (post-hoc) ---


def _turns(rec, rounds):
    """rounds: list of (a1, a2, a3) letters per round."""
    rec["turns"] = [
        {
            "round": r,
            "label": f"Debater {i}",
            "provider": "p",
            "model": f"m{i}",
            "fallback_used": False,
            "answer": ans,
        }
        for r, answers in enumerate(rounds)
        for i, ans in enumerate(answers, start=1)
    ]
    return rec


def _judge(rec, letter, d_correct, b_correct=False):
    rec["conditions"]["D"].update(answer=letter, correct=d_correct)
    rec["conditions"]["B"].update(correct=b_correct)
    return rec


def test_swap_and_oscillation_detection():
    swap = _turns(record("s", {}), [("A", "B", "C"), ("B", "A", "C")])
    osc = _turns(record("o", {}), [("A", "B", "B"), ("C", "B", "B"), ("A", "B", "B")])
    one_change = _turns(record("c", {}), [("A", "B", "B"), ("B", "B", "B")])
    stable = _turns(record("t", {}), [("A", "B", "C"), ("A", "B", "C")])
    invalid = _turns(record("i", {}), [("A", None, "C"), (None, "A", "C")])
    assert report.swap_or_oscillation(swap) == (True, False)
    assert report.swap_or_oscillation(osc) == (False, True)
    assert report.swap_or_oscillation(one_change) == (False, False)
    assert report.swap_or_oscillation(stable) == (False, False)
    assert report.swap_or_oscillation(invalid) == (False, False)


def test_final_plurality_flags_ties_and_ignores_invalid():
    def plurality(rounds):
        return report.final_plurality(_turns(record("x", {}), rounds))

    assert plurality([("A", "B", "C"), ("B", "B", "C")]) == ("B", False)
    assert plurality([("A", "B", "C")]) == ("A", True)
    assert plurality([("A", "B", "B"), (None, None, "D")]) == ("D", False)
    assert plurality([("A", "B", "C"), (None, None, None)]) == (None, False)
    assert report.final_plurality(record("e", {})) == (None, False)  # no saved turns


def test_dynamics_section_counts_and_is_labelled_exploratory():
    recs = [
        # swap (also q1); unique plurality B (gold B); judge says B: agrees
        _judge(_turns(record("q0", {}, gold="B"), [("A", "B", "C"), ("B", "A", "B")]), "B", True),
        # plurality C wrong (gold A); judge A right and differs
        _judge(_turns(record("q1", {}, gold="A"), [("A", "C", "C"), ("C", "C", "A")]), "A", True),
        # tie in last round; judge differs but not scored
        _judge(_turns(record("q2", {}, gold="A"), [("A", "B", "C")]), "A", True),
        # plurality D (gold D) right; judge C wrong and differs
        _judge(_turns(record("q3", {}, gold="D"), [("D", "D", "C"), ("D", "D", "C")]), "C", False),
        # plurality and judge both wrong and different
        _judge(_turns(record("q4", {}, gold="A"), [("B", "B", "C"), ("B", "B", "C")]), "C", False),
    ]
    text = report.exploratory_dynamics_section(recs)
    assert "Exploratory, post-hoc, not pre-declared" in text
    assert "only pre-declared comparison" in text
    assert "with a swap" in text and "swap" in text
    assert "exchange two different valid answers between consecutive rounds): 2/5" in text
    # q0 last round is (B, A, B): plurality B right; q1 (C, C, A): C wrong; q3 D right; q4 B wrong
    plural_row = next(ln for ln in text.splitlines() if ln.startswith("| Plurality unique"))
    cells = [c.strip() for c in plural_row.strip("|").split("|")]
    assert cells[1:] == ["4", "2/4", "2/4", "0/4"]
    tied_row = next(ln for ln in text.splitlines() if ln.startswith("| Plurality tied"))
    assert [c.strip() for c in tied_row.strip("|").split("|")][1] == "1"
    # judge differs from plurality on q1, q3, q4 (3 of 4); judge right q1, plurality right q3
    assert "differed from the plurality on 3/4" in text
    assert "judge right 1, plurality right 1, neither 1" in text


def test_dynamics_sections_only_in_letter_dataset_report():
    numeric = build_report([record("q0", {})], MANIFEST)
    assert "debate dynamics" not in numeric
    letters = {"config": {**MANIFEST["config"], "dataset": "mmlupro-holdout"}}
    recs = [
        _judge(_turns(record("q0", {}), [("A", "B", "C"), ("B", "A", "C")]), "A", True),
    ]
    for r in recs:
        for k in ("A1", "A2", "A3"):
            r["conditions"][k]["answer"] = "A"
    text = build_report(recs, letters)
    assert "#### Exploratory: debate dynamics (post-hoc)" in text
    assert "#### Exploratory: disagreement by round-0 outcome" in text


# --- report text: output limits and joined words ---

MMLU_CONFIG = Path(report.__file__).parent / "config" / "mmlupro_agents.yaml"
MMLU_MANIFEST = {
    "config": {
        "dataset": "mmlupro-holdout",
        "seed": 42,
        "prompt_suffix": "Answer with only the letter (A to {last}) of the correct option.",
        "agents_fingerprint": "abc123",
        "allow_fallback": False,
        "early_stop": True,
        "profile": {"max_tokens": 2048, "rpm": {"groq": 4}},
    }
}


def test_limit_text_states_the_headline_and_the_exceptions():
    limits = {"debater_1": 2048, "debater_2": 2048, "debater_3": 4096, "judge": 2048}
    assert report.limit_text(2048, limits) == "2048 tokens per answer (4096 for Debater 3)"
    assert report.limit_text(2048, {"debater_1": 2048, "judge": 2048}) == "2048 tokens per answer"
    assert report.limit_text(2048, None) == "2048 tokens per answer"


def test_effective_limits_are_a_floor_over_the_config(tmp_path):
    limits = report.effective_limits(MMLU_CONFIG, {"max_tokens": 2048})
    assert limits == {"debater_1": 2048, "debater_2": 2048, "debater_3": 4096, "judge": 2048}
    # a higher floor lifts everyone; an agent set above the floor keeps its own value
    assert set(report.effective_limits(MMLU_CONFIG, {"max_tokens": 8192}).values()) == {8192}
    assert report.effective_limits(MMLU_CONFIG, {}) is None
    assert report.effective_limits(tmp_path / "missing.yaml", {"max_tokens": 2048}) is None


def test_header_and_cut_off_limitation_state_per_agent_limits():
    text = build_report([record("q0", {})], MMLU_MANIFEST, agents_config=MMLU_CONFIG)
    assert "output limit 2048 tokens per answer (4096 for Debater 3)" in text
    assert "raised to 2048 tokens per answer (4096 for Debater 3) in the eval's own" in text
    assert "2048 tokens per answer in the eval" not in text


def test_limit_text_falls_back_to_the_floor_when_the_config_is_unreadable(tmp_path):
    text = build_report([record("q0", {})], MMLU_MANIFEST, agents_config=tmp_path / "missing.yaml")
    assert "output limit 2048 tokens per answer," in text
    assert "raised to 2048 tokens per answer in the eval" in text


def test_limitations_text_has_balanced_parentheses_and_no_joined_words():
    import re

    for dataset in ("gsm8k", "math45", "mmlupro-holdout"):
        block = report.limitations(
            dataset, "Answer with only the letter (A to D).", {"max_tokens": 2048}, True
        )
        for line in block.splitlines():
            assert line.count("(") == line.count(")"), line
        assert not re.findall(r"[a-z][.;:,)][A-Za-z]", block.replace("e.g.", ""))
    text = build_report([record("q0", {})], MMLU_MANIFEST, agents_config=MMLU_CONFIG)
    assert not re.findall(r"[a-z][;:,][A-Za-z0-9]", text)
