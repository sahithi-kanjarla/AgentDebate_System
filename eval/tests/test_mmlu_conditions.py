"""Conditions without C, answers that may not vote, and the matching call estimate."""

from app.core.settings import load_agents
from eval.budget import estimate_per_question
from eval.conditions import derive
from eval.scoring import score_letter
from eval.tests.test_conditions import run
from tests.conftest import MOCK_AGENTS


def valid(a: str) -> bool:
    return len(a) == 1 and a in "ABCDEFGHIJ"


def scorer(a):
    return score_letter(a, "B", valid)


def test_without_c_only_a_b_and_d_exist():
    d = run([["B", "A", "A"], ["B", "B", "B"]], verdict="B")
    out = derive("q", 42, scorer, d, None, include_c=False, valid=valid)
    assert set(out) == {"A1", "A2", "A3", "B", "D"}
    assert out["B"].answer == "A" and not out["B"].correct and out["D"].correct


def test_default_still_derives_c_and_d_vote():
    d = run([["B", "A", "A"], ["B", "B", "B"]], verdict="B")
    assert {"C", "D_vote"} <= set(derive("q", 42, scorer, d, None))


def test_an_invalid_answer_scores_invalid_but_does_not_vote():
    d = run([["Option A", "B", "C"], ["B", "B", "B"]], verdict="B")
    out = derive("q", 42, scorer, d, None, include_c=False, valid=valid)
    assert out["A1"].status == "invalid" and not out["A1"].correct
    assert out["B"].note == "tie"  # B and C tie; "Option A" is not a vote
    d = run([["Option A", "Option A", "B"], ["B", "B", "B"]], verdict="B")
    out = derive("q", 42, scorer, d, None, include_c=False, valid=valid)
    assert out["B"].answer == "B" and out["B"].note is None  # the two invalid replies do not win


def test_all_invalid_gives_no_answer():
    d = run([["x", "y", "z"], ["B", "B", "B"]], verdict="B")
    out = derive("q", 42, scorer, d, None, include_c=False, valid=valid)
    assert out["B"].answer is None and out["B"].status == "missing"
    assert out["B"].note == "no_valid_answers"


def test_the_call_estimate_has_one_judge_call_without_c():
    agents = load_agents(MOCK_AGENTS)  # all on the "mock" provider
    with_c = estimate_per_question(agents, 3, 1)
    no_c = estimate_per_question(agents, 3, 1, include_c=False)
    # three debaters for 2 to 4 rounds, plus the judge
    assert with_c["mock"] == (3 * 2 + 1, 3 * 4 + 2)
    assert no_c["mock"] == (3 * 2 + 1, 3 * 4 + 1)
