"""MMLU-Pro loader, letter extraction, fixed selections and the whole run on 3 rows. No network."""

import contextlib
import io
import json
import re
import urllib.error

import pytest

from eval import mmlupro
from eval.conditions import majority
from eval.datasets import DatasetError, get_dataset
from eval.mmlupro import (
    MMLUProHoldout,
    MMLUProScreen,
    assert_disjoint,
    extract_letter,
    fetch,
    load_rows,
    normalize_letter,
    select,
    selection_path,
)
from eval.report import build_report, load_run
from eval.run import main
from eval.tests.helpers import factory
from eval.tests.mmlu_helpers import (
    MMLU_CATEGORIES,
    mmlu_row,
    mmlu_rows,
    write_mmlu_data,
    write_mmlu_selection,
)

# --- letter extraction ---


@pytest.mark.parametrize(
    ("text", "letter"),
    [
        ("B", "B"),
        ("b", "B"),
        ("  B  ", "B"),
        ("(B)", "B"),
        ("B.", "B"),
        ("(B).", "B"),
        ("( C )", "C"),
        ("J", "J"),
        ("The answer is C", "C"),
        ("the answer is (D).", "D"),
        ("So the answer is: E", "E"),
        ("Answer is F.", "F"),
        # rejected
        ("", None),
        ("K", None),
        ("AB", None),
        ("Option B", None),
        ("B because it is larger", None),
        ("The answer is C because of x", None),  # the letter must end the text
        ("((B))", None),  # only one pair of parentheses is dropped
        ("B..", None),  # only one period is dropped
        ("The answer is a good one", None),  # a lower-case article is not a letter
        ("42", None),
    ],
)
def test_extract_letter(text, letter):
    assert extract_letter(text) == letter


@pytest.mark.parametrize(
    ("text", "n_options", "letter"),
    [
        ("D", 4, "D"),
        ("(d).", 4, "D"),
        ("The answer is D", 4, "D"),
        ("E", 4, None),  # a 4-option question has no E
        ("J", 4, None),
        ("The answer is H", 4, None),
        ("(J)", 10, "J"),
        ("C", 3, "C"),
        ("D", 3, None),
        ("B", 2, "B"),
        ("C", 2, None),
    ],
)
def test_extract_letter_only_accepts_the_questions_own_range(text, n_options, letter):
    assert extract_letter(text, n_options) == letter
    assert (mmlupro.normalize_letter(text, n_options) == letter) or letter is None
    assert mmlupro.letters_for(n_options) == "ABCDEFGHIJ"[:n_options]


def test_normalizer_returns_the_letter_or_the_text_unchanged():
    assert normalize_letter("(c).") == "C"
    assert normalize_letter("Option B") == "Option B"


# --- download ---


class FakeHF:
    """The datasets-server rows API and the dataset info endpoint, in memory."""

    def __init__(self, rows, *, total=None, fail_first=0, page_override=None, errors=()):
        self.rows, self.total = rows, len(rows) if total is None else total
        self.errors = list(errors)  # raised, in order, by the first requests
        self.fail_first, self.page_override = fail_first, page_override or {}
        self.urls: list[str] = []

    def __call__(self, url, timeout=60):
        self.urls.append(url)
        if self.errors:
            raise self.errors.pop(0)
        if self.fail_first > 0:
            self.fail_first -= 1
            raise OSError("connection reset")
        if "api/datasets" in url:
            body = {"sha": "rev123"}
        else:
            offset = int(re.search(r"offset=(\d+)", url).group(1))
            length = int(re.search(r"length=(\d+)", url).group(1))
            assert length <= 100
            chunk = self.page_override.get(offset, self.rows[offset : offset + length])
            body = {
                "num_rows_total": self.total,
                "rows": [
                    {"row_idx": offset + i, "row": r, "truncated_cells": []}
                    for i, r in enumerate(chunk)
                ],
            }
        return contextlib.closing(io.BytesIO(json.dumps(body).encode("utf-8")))


@pytest.fixture
def small(monkeypatch):
    monkeypatch.setattr(mmlupro, "EXPECTED_ROWS", 250)
    return mmlu_rows(50)  # 5 x 50 rows: three pages of 100, 100, 50


def test_fetch_pages_validates_and_pins(small, tmp_path):
    hf = FakeHF(small)
    manifest = fetch(tmp_path, hf, sleep=lambda s: None)
    assert manifest["rows"] == 250 and manifest["revision"] == "rev123"
    pages = [u for u in hf.urls if "offset=" in u]
    assert [int(re.search(r"offset=(\d+)", u).group(1)) for u in pages] == [0, 100, 200]
    rows, sha = load_rows(tmp_path)
    assert sha == manifest["source_sha256"] and len(rows) == 250
    # same data again: same pin, nothing changes
    assert fetch(tmp_path, FakeHF(small), sleep=lambda s: None)["source_sha256"] == sha


def nothing_written(data_dir):
    """No dataset file and no pin; saved pages of a failed download may remain for a resume."""
    return (
        not (data_dir / mmlupro.RAW_NAME).exists()
        and not (data_dir / mmlupro.MANIFEST_NAME).exists()
    )


def too_many(retry_after=None):
    headers = {"Retry-After": retry_after} if retry_after else {}
    return urllib.error.HTTPError("http://x", 429, "Too Many Requests", headers, None)


def test_fetch_honours_retry_after_on_a_429(small, tmp_path):
    slept: list[float] = []
    hf = FakeHF(small, errors=[too_many("7"), too_many("3")])
    manifest = fetch(tmp_path, hf, sleep=slept.append)
    assert manifest["rows"] == 250
    assert slept[:2] == [7.0, 3.0]  # the server's own wait, not our backoff


def test_a_429_without_retry_after_backs_off_with_jitter_up_to_a_minute(small, tmp_path):
    slept: list[float] = []
    hf = FakeHF(small, errors=[too_many() for _ in range(6)])
    fetch(tmp_path, hf, sleep=slept.append)
    waits = slept[:6]
    assert all(0 < w <= mmlupro.BACKOFF_CAP_S for w in waits)
    assert waits[-1] > waits[0] and waits[-1] >= 0.75 * 60  # grows, then sits near the cap


def test_a_huge_retry_after_is_capped(small, tmp_path):
    slept: list[float] = []
    fetch(tmp_path, FakeHF(small, errors=[too_many("99999")]), sleep=slept.append)
    assert slept[0] == mmlupro.RETRY_AFTER_CAP_S


def test_fetch_gives_up_after_repeated_429s_and_writes_nothing(small, tmp_path):
    hf = FakeHF(small, errors=[too_many("1") for _ in range(99)])
    with pytest.raises(DatasetError, match="download failed.*429"):
        fetch(tmp_path, hf, sleep=lambda s: None)
    assert nothing_written(tmp_path)


def test_fetch_paces_pages(small, tmp_path):
    slept: list[float] = []
    fetch(tmp_path, FakeHF(small), sleep=slept.append)
    assert slept == [mmlupro.PAGE_PAUSE_S] * 2  # between 3 pages, none before the first


def test_a_rerun_resumes_from_the_saved_pages_and_cleans_up(small, tmp_path):
    # the server keeps failing from offset 200 on: pages 0 and 100 are saved
    failing = FakeHF(small, errors=[])

    def flaky(url, timeout=60):
        if "offset=200" in url:
            raise OSError("down")
        return failing(url, timeout)

    with pytest.raises(DatasetError, match="download failed"):
        fetch(tmp_path, flaky, sleep=lambda s: None)
    pages_dir = tmp_path / mmlupro.PAGES_DIR_NAME
    assert sorted(p.name for p in pages_dir.iterdir()) == [
        "page_000000.json",
        "page_000100.json",
    ]
    assert nothing_written(tmp_path)

    hf = FakeHF(small)
    manifest = fetch(tmp_path, hf, sleep=lambda s: None)
    requested = [u for u in hf.urls if "offset=" in u]
    assert len(requested) == 1 and "offset=200" in requested[0]  # cached pages were not fetched
    assert manifest["rows"] == 250 and load_rows(tmp_path)[1] == manifest["source_sha256"]
    assert not pages_dir.exists()  # removed once the validated file is written
    # the resumed file equals a clean download
    clean = tmp_path / "clean"
    assert (
        fetch(clean, FakeHF(small), sleep=lambda s: None)["source_sha256"]
        == (manifest["source_sha256"])
    )


def test_a_corrupt_saved_page_is_fetched_again(small, tmp_path):
    pages_dir = tmp_path / mmlupro.PAGES_DIR_NAME
    pages_dir.mkdir()
    (pages_dir / "page_000000.json").write_text("{not json", encoding="utf-8")
    (pages_dir / "page_000100.json").write_text(
        json.dumps({"num_rows_total": 250, "rows": []}), encoding="utf-8"
    )
    hf = FakeHF(small)
    assert fetch(tmp_path, hf, sleep=lambda s: None)["rows"] == 250
    assert len([u for u in hf.urls if "offset=" in u]) == 3


def test_fetch_retries_a_flaky_connection(small, tmp_path):
    slept: list[float] = []
    fetch(tmp_path, FakeHF(small, fail_first=2), sleep=slept.append)
    assert [x for x in slept if x != mmlupro.PAGE_PAUSE_S] == [1.0, 2.0]


def test_fetch_gives_up_and_writes_nothing(small, tmp_path):
    with pytest.raises(DatasetError, match="download failed"):
        fetch(tmp_path, FakeHF(small, fail_first=99), sleep=lambda s: None)
    assert nothing_written(tmp_path)


@pytest.mark.parametrize(
    ("make", "message"),
    [
        (lambda rows: FakeHF(rows, total=249), "expected 250 rows"),
        (lambda rows: FakeHF(rows, page_override={100: rows[100:150]}), "short page"),
        (lambda rows: FakeHF(rows[:-1], total=250), "short page"),
        (
            lambda rows: FakeHF([{**rows[0], "answer": "Z"}, *rows[1:]]),
            "outside its 4 options",
        ),
        (
            lambda rows: FakeHF([{**rows[0], "answer": "E"}, *rows[1:]]),
            "outside its 4 options",
        ),
        (lambda rows: FakeHF([{"question": "x"}, *rows[1:]]), "missing required fields"),
        (lambda rows: FakeHF([rows[0], rows[0], *rows[2:]]), "duplicate question_id"),
        (
            lambda rows: FakeHF([{**rows[0], "options": ["only one"]}, *rows[1:]]),
            "malformed options",
        ),
    ],
)
def test_fetch_refuses_a_short_or_malformed_download(small, tmp_path, make, message):
    with pytest.raises(DatasetError, match=message):
        fetch(tmp_path, make(small), sleep=lambda s: None)
    assert nothing_written(tmp_path)


def test_fetch_refuses_a_changed_upstream_and_keeps_the_pin(small, tmp_path):
    first = fetch(tmp_path, FakeHF(small), sleep=lambda s: None)
    changed = [{**small[0], "question": "different text"}, *small[1:]]
    with pytest.raises(DatasetError, match="upstream dataset changed"):
        fetch(tmp_path, FakeHF(changed), sleep=lambda s: None)
    assert load_rows(tmp_path)[1] == first["source_sha256"]


def test_load_refuses_a_file_that_does_not_match_its_pin(small, tmp_path):
    fetch(tmp_path, FakeHF(small), sleep=lambda s: None)
    raw = tmp_path / mmlupro.RAW_NAME
    raw.write_bytes(raw.read_bytes().replace(b"option A", b"option X", 1))
    with pytest.raises(DatasetError, match="does not match the pin"):
        load_rows(tmp_path)


def test_load_keeps_rows_whose_text_has_unicode_line_separators(tmp_path):
    rows = mmlu_rows(2)
    rows[3]["question"] = "beforeafter   and   end"
    write_mmlu_data(tmp_path, rows)
    loaded, _ = load_rows(tmp_path)
    assert len(loaded) == len(rows) and loaded[3]["question"] == rows[3]["question"]


def test_load_refuses_without_a_fetch(tmp_path):
    with pytest.raises(DatasetError, match="run: python -m eval.mmlupro fetch"):
        load_rows(tmp_path)


# --- selections ---


@pytest.fixture
def data_dir(tmp_path):
    write_mmlu_data(tmp_path, mmlu_rows(40))
    return tmp_path


def ids_of(path):
    sel = json.loads(path.read_text(encoding="utf-8"))
    return sel, {i for ids in sel["ids"].values() for i in ids}


def test_holdout_is_twelve_per_category_and_deterministic(data_dir):
    path, created = select("holdout", mmlupro.HOLDOUT_SEED, data_dir)
    assert created
    sel, ids = ids_of(path)
    assert list(sel["ids"]) == list(MMLU_CATEGORIES)
    assert all(len(v) == 12 for v in sel["ids"].values()) and len(ids) == 60
    path2, created2 = select("holdout", mmlupro.HOLDOUT_SEED, data_dir)
    assert path2 == path and not created2  # verified, not rewritten
    # each id sits in the category it is listed under
    by_id = {r["question_id"]: r["category"] for r in load_rows(data_dir)[0]}
    assert all(by_id[i] == cat for cat, v in sel["ids"].items() for i in v)


def test_screen_and_holdout_are_disjoint_and_a_rescreen_is_too(data_dir):
    holdout, _ = select("holdout", mmlupro.HOLDOUT_SEED, data_dir)
    screen, _ = select("screen", 42, data_dir)
    rescreen, _ = select("screen", 43, data_dir)
    _, h = ids_of(holdout)
    _, s1 = ids_of(screen)
    _, s2 = ids_of(rescreen)
    assert len(h) == len(s1) == len(s2) == 60
    assert not h & s1 and not h & s2 and not s1 & s2
    assert_disjoint(mmlupro.all_selection_files(data_dir))


def test_a_screen_needs_the_holdout_first(data_dir):
    with pytest.raises(DatasetError, match="select the holdout first"):
        select("screen", 42, data_dir)


def test_a_holdout_drawn_after_a_screen_avoids_it(data_dir):
    write_mmlu_selection(
        data_dir,
        load_rows(data_dir)[1],
        {c: [1000 * i + k for k in range(12)] for i, c in enumerate(MMLU_CATEGORIES)},
    )
    holdout, _ = select("holdout", mmlupro.HOLDOUT_SEED, data_dir)
    _, h = ids_of(holdout)
    _, s = ids_of(selection_path("screen", 42, data_dir))
    assert not h & s


def test_an_existing_selection_is_never_overwritten(data_dir):
    path, _ = select("holdout", mmlupro.HOLDOUT_SEED, data_dir)
    sel = json.loads(path.read_text(encoding="utf-8"))
    sel["ids"]["law"][0] = 99999
    path.write_text(json.dumps(sel), encoding="utf-8")
    with pytest.raises(DatasetError, match="differs from a fresh draw"):
        select("holdout", mmlupro.HOLDOUT_SEED, data_dir)


def test_a_pool_that_is_too_small_is_refused(tmp_path):
    write_mmlu_data(tmp_path, mmlu_rows(11))
    with pytest.raises(DatasetError, match="need 12"):
        select("holdout", mmlupro.HOLDOUT_SEED, tmp_path)


def test_assert_disjoint_catches_overlap_and_repeats():
    a = {"ids": {"law": [1, 2]}}
    with pytest.raises(DatasetError, match="in both"):
        assert_disjoint({"x.json": a, "y.json": {"ids": {"law": [2, 3]}}})
    with pytest.raises(DatasetError, match="twice"):
        assert_disjoint({"x.json": {"ids": {"law": [1, 1]}}})


def test_datasets_refuse_to_load_when_screen_and_holdout_overlap(data_dir):
    select("holdout", mmlupro.HOLDOUT_SEED, data_dir)
    holdout_ids = ids_of(selection_path("holdout", mmlupro.HOLDOUT_SEED, data_dir))[0]["ids"]
    write_mmlu_selection(data_dir, load_rows(data_dir)[1], holdout_ids, kind="screen")
    with pytest.raises(DatasetError, match="in both"):
        MMLUProScreen(data_dir).load()
    with pytest.raises(DatasetError, match="in both"):
        MMLUProHoldout(data_dir).load()


def test_dataset_questions_carry_options_gold_and_meta(data_dir):
    select("holdout", mmlupro.HOLDOUT_SEED, data_dir)
    select("screen", 42, data_dir)
    ds = MMLUProScreen(data_dir)
    qs = ds.load()
    assert len(qs) == 60
    q = qs[0]
    assert q.qid == f"mmlupro-{q.meta['question_id']}" and q.meta["category"] == "chemistry"
    assert "\nA. option A of" in q.text and "\nD. option D of" in q.text
    assert q.gold in "ABCD" and q.meta["n_options"] == 4
    assert ds.prompt(q).endswith("Answer with only the letter (A to D) of the correct option.")
    assert mmlupro.PROMPT_SUFFIX.format(last="D") in ds.prompt(q)


def test_the_suffix_and_the_accepted_letters_follow_each_questions_option_count(tmp_path):
    rows = [
        mmlu_row(1, "chemistry", "D", 4),
        mmlu_row(2, "chemistry", "J", 10),
        mmlu_row(3, "chemistry", "F", 6),
    ]
    sha = write_mmlu_data(tmp_path, rows)
    write_mmlu_selection(tmp_path, sha, {"chemistry": [1, 2, 3]})
    ds = MMLUProScreen(tmp_path)
    q4, q10, q6 = ds.load()
    assert ds.prompt(q4).endswith("(A to D) of the correct option.")
    assert ds.prompt(q10).endswith("(A to J) of the correct option.")
    assert ds.prompt(q6).endswith("(A to F) of the correct option.")
    # the same letter is a valid answer for one question and invalid for another
    assert ds.score(q10, "J").status == "correct" and ds.score(q4, "J").status == "invalid"
    assert ds.score(q4, "(D).").status == "correct" and ds.score(q6, "G").status == "invalid"
    assert ds.normalize_answer("(d).", q4) == "D" and ds.normalize_answer("E", q4) == "E"
    assert ds.is_valid_answer("D", q4) and not ds.is_valid_answer("E", q4)
    assert ds.is_valid_answer("E", q10) and ds.is_valid_answer("E", q6)
    assert not ds.is_valid_answer("G", q6)


def test_dataset_scoring(data_dir):
    select("holdout", mmlupro.HOLDOUT_SEED, data_dir)
    select("screen", 42, data_dir)
    ds = MMLUProScreen(data_dir)
    q = ds.load()[0]
    other = "A" if q.gold != "A" else "B"
    assert ds.score(q, f"({q.gold}).").status == "correct"
    assert ds.score(q, other).status == "wrong"
    assert ds.score(q, "Option " + q.gold).status == "invalid"
    assert ds.score(q, None).status == "missing"


def test_registered_names():
    assert isinstance(get_dataset("mmlupro-screen"), MMLUProScreen)
    assert isinstance(get_dataset("mmlupro-holdout"), MMLUProHoldout)


# --- plurality ---


def test_majority_tie_break_does_not_depend_on_answer_order():
    for salt in range(20):
        a = majority(["C", "A", "B"], f"s{salt}")
        assert a == majority(["B", "C", "A"], f"s{salt}") == majority(["A", "B", "C"], f"s{salt}")
        assert a[1] is True


# --- the whole run on 3 rows, no network ---


def three_row_data(tmp_path):
    rows = [mmlu_row(i, "chemistry", "ABC"[i], 4) for i in range(3)]
    data_dir = tmp_path / "data"
    sha = write_mmlu_data(data_dir, rows)
    write_mmlu_selection(data_dir, sha, {"chemistry": [0, 1, 2]})
    return MMLUProScreen(data_dir)


def behave(c):
    """q0 gold A: round 0 is a three-way split, then everyone converges in different spellings.
    q1 gold B: unanimous. q2 gold C: one invalid reply, the two valid ones disagree."""
    gold = "ABC"[c.q]
    idx = int(c.agent_id.split("_")[1]) - 1 if c.role == "debater" else 0
    if c.role == "judge":
        return f"({gold})."
    if c.q == 0:
        return (["A", "B", "C"] if c.round == 0 else ["(A)", "a", "The answer is A"])[idx]
    if c.q == 1:
        return ["B.", "B", "(b)"][idx]
    return ["Option C", "C", "D"][idx] if c.round == 0 else "C"


def test_three_row_run_end_to_end(tmp_path, settings):
    dataset = three_row_data(tmp_path)
    out: list[str] = []
    fac = factory(behave)

    async def no_sleep(_s):
        return None

    code = main(
        ["--dataset", "mmlupro-screen", "--n", "3", "--yes", "--sleep-between-s", "1"],
        provider_factory=fac,
        dataset=dataset,
        settings=settings,
        sleep=no_sleep,
        results_dir=tmp_path / "results",
        cache_dir=tmp_path / "cache",
        data_dir=tmp_path / "data",
        out=out.append,
    )
    assert code == 0, out
    run_dir = tmp_path / "results" / "mmlupro-screen-s42"
    records = {
        r["qid"]: r
        for r in (json.loads(p.read_text("utf-8")) for p in (run_dir / "questions").glob("*.json"))
    }
    assert set(records) == {"mmlupro-0", "mmlupro-1", "mmlupro-2"}
    for r in records.values():  # no C, no D-vote
        assert set(r["conditions"]) == {"A1", "A2", "A3", "B", "D"}
        assert r["judge_c"] is None
    manifest = json.loads((run_dir / "manifest.json").read_text("utf-8"))
    assert manifest["config"]["include_c"] is False

    q0, q1, q2 = (records[f"mmlupro-{i}"] for i in range(3))
    c0 = q0["conditions"]
    assert [c0[k]["answer"] for k in ("A1", "A2", "A3")] == ["A", "B", "C"]
    assert c0["B"]["note"] == "tie" and c0["D"]["answer"] == "A" and c0["D"]["correct"]
    # the round-1 spellings "(A)", "a" and "The answer is A" count as agreement
    assert q0["facts"]["rounds_run"] == 1 and q0["facts"]["early_stopped"]
    r1 = {t["label"]: t["answer"] for t in q0["turns"] if t["round"] == 1}
    assert set(r1.values()) == {"A"}
    assert all(q1["conditions"][k]["answer"] == "B" for k in ("A1", "A2", "A3"))
    assert q1["conditions"]["B"]["correct"] and q1["facts"]["early_stopped"]
    c2 = q2["conditions"]
    assert c2["A1"]["answer"] == "Option C" and c2["A1"]["status"] == "invalid"
    assert c2["B"]["note"] == "tie"  # the invalid reply did not vote; C and D tie
    assert c2["D"]["answer"] == "C" and c2["D"]["correct"]
    # one judge call per question: no C judge
    assert len(fac.made["judge"].calls) == 3

    records_list, manifest, skipped = load_run(run_dir)
    report = build_report(records_list, manifest, skipped)
    assert "D-vote" not in report and "C debate" not in report
    assert "#### Answer letters" in report and "tie rate" in report
    assert "Accuracy by category" in report and "Not compute-matched" in report
    assert "D vs B" in report and "B vs A1" not in report  # D vs B is the only test
    assert "Invalid answers (not a letter A-J)" in report


def test_a_letter_outside_the_questions_options_is_invalid_and_does_not_vote(tmp_path, settings):
    dataset = three_row_data(tmp_path)  # three 4-option questions
    fac = factory(
        lambda c: "J" if c.agent_id == "debater_1" else "A" if c.role == "debater" else "A"
    )

    async def no_sleep(_s):
        return None

    out: list[str] = []
    code = main(
        ["--dataset", "mmlupro-screen", "--n", "1", "--yes", "--sleep-between-s", "1"],
        provider_factory=fac,
        dataset=dataset,
        settings=settings,
        sleep=no_sleep,
        results_dir=tmp_path / "results",
        cache_dir=tmp_path / "cache",
        data_dir=tmp_path / "data",
        out=out.append,
    )
    assert code == 0, out
    rec = next((tmp_path / "results" / "mmlupro-screen-s42" / "questions").glob("*.json"))
    rec = json.loads(rec.read_text("utf-8"))
    assert rec["conditions"]["A1"]["status"] == "invalid"  # J is not one of 4 options
    assert rec["conditions"]["B"]["answer"] == "A" and rec["conditions"]["B"]["note"] is None
    sent = fac.made["debater_1"].calls[0].text
    assert "Answer with only the letter (A to D) of the correct option." in sent
