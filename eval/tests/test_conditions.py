from decimal import Decimal

from eval.conditions import Cost, RunData, TurnInfo, derive, majority, prefix_consistent
from eval.scoring import score_number


def turn(rnd, n, answer, fb=False):
    return TurnInfo(
        rnd, f"Debater {n}", "p", "prov", "m", fb, answer is not None, answer, 80, 10, 5, 100
    )


def run(rounds, verdict="10", judge_fb=False, judge_failed=False):
    """rounds: list of [a1, a2, a3] per round."""
    turns = [turn(r, i + 1, a) for r, answers in enumerate(rounds) for i, a in enumerate(answers)]
    snaps = {
        r: Cost(3 * (r + 1), 3 * (r + 1), 45 * (r + 1), 1000 * (r + 1), 0)
        for r in range(len(rounds))
    }
    last = len(rounds) - 1
    judge = TurnInfo(last + 1, "Judge", "j", "prov", "m", judge_fb, True, verdict, 90, 20, 5, 500)
    total = snaps[last] + Cost(1, 1, 25, 500, 0)
    return RunData(turns, judge, verdict, judge_failed, last, snaps, total)


def scorer(a):
    return score_number(a, Decimal(10))


def test_majority_picks_the_larger_group_and_compares_numbers_by_value():
    assert majority(["10", "10.0", "7"], "s") == ("10", False)
    assert majority(["$10", "7", "10"], "s")[0] == "$10"


def test_majority_ignores_missing_votes_and_all_missing_is_none():
    assert majority([None, "7", "7"], "s") == ("7", False)
    assert majority([None, None, None], "s") == (None, False)
    assert majority([None, "7", None], "s") == ("7", False)


def test_majority_tie_is_flagged_and_deterministic_for_a_salt():
    first = majority(["1", "2", "3"], "42:q:B")
    assert first[1] is True
    assert all(majority(["1", "2", "3"], "42:q:B") == first for _ in range(20))
    picks = {majority(["1", "2", "3"], f"42:q{i}:B")[0] for i in range(40)}
    assert picks == {"1", "2", "3"}  # not a fixed debater
    assert majority(["1", "2", None], "s")[1] is True  # two valid answers that disagree


def test_a_b_c_d_and_d_vote_come_from_the_recorded_rounds():
    d = run([["10", "7", "7"], ["10", "10", "7"], ["10", "10", "10"]], verdict="10")
    c = run([["10", "7", "7"], ["10", "10", "7"]], verdict="7")
    out = derive("q", 42, scorer, d, c)
    assert [out[k].correct for k in ("A1", "A2", "A3")] == [True, False, False]
    assert out["B"].answer == "7" and not out["B"].correct
    assert out["C"].answer == "7" and not out["C"].correct
    assert out["D"].correct and out["D_vote"].correct


def test_cost_of_c_is_d_rounds_0_to_1_plus_the_c_judge_call():
    d = run([["10", "7", "7"], ["10", "10", "7"], ["10", "10", "10"]])
    c = run([["10", "7", "7"], ["10", "10", "7"]])
    out = derive("q", 42, scorer, d, c)
    assert out["B"].cost == d.snapshots[0]
    assert out["C"].cost == d.snapshots[1] + Cost(1, 1, 25, 500, 0)
    assert out["D"].cost == d.total
    assert out["D_vote"].cost == d.snapshots[2]  # debate without the judge
    assert out["A1"].cost == Cost(1, 1, 15, 100, 0)


def test_c_equals_d_when_d_stopped_after_round_1():
    d = run([["10", "10", "10"], ["10", "10", "10"]], verdict="10")
    out = derive("q", 42, scorer, d, None)
    assert out["C"].answer == out["D"].answer and out["C"].cost == out["D"].cost


def test_invalid_and_non_numeric_answers_are_wrong():
    d = run([[None, "10 dollars", "10"], ["10", "10", "10"]], verdict="10")
    out = derive("q", 42, scorer, d, None)
    assert out["A1"].status == "missing" and not out["A1"].correct
    assert out["A2"].status == "non_numeric" and not out["A2"].correct
    assert out["A3"].correct
    assert out["B"].note == "tie"  # "10 dollars" and "10" are single votes


def test_fallback_flags_follow_the_contributing_turns():
    d = run([["10", "10", "10"], ["10", "10", "10"]])
    d.turns[1].fallback_used = True  # Debater 2, round 0
    out = derive("q", 42, scorer, d, None)
    assert out["A1"].fallback is False and out["A2"].fallback is True
    assert out["B"].fallback and out["D"].fallback and out["C"].fallback


def test_judge_failure_is_noted_on_c_and_d():
    d = run([["10", "10", "10"], ["10", "10", "10"]], judge_failed=True)
    out = derive("q", 42, scorer, d, None)
    assert out["C"].note == out["D"].note == "judge_failed"


def test_prefix_consistency_detects_a_different_replay():
    d = run([["10", "7", "7"], ["10", "10", "7"], ["10", "10", "10"]])
    same = run([["10", "7", "7"], ["10", "10", "7"]])
    other = run([["10", "7", "7"], ["10", "10", "9"]])
    assert prefix_consistent(d, same) and not prefix_consistent(d, other)
