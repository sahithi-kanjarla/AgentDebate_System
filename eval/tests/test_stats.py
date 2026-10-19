import pytest

from eval.stats import compare, mcnemar_exact, paired_bootstrap, reading, wilson


def test_wilson_known_values():
    lo, hi = wilson(5, 10)
    assert (round(lo, 4), round(hi, 4)) == (0.2366, 0.7634)
    lo, hi = wilson(0, 3)
    assert lo == 0.0 and round(hi, 4) == 0.5615
    lo, hi = wilson(3, 3)
    assert round(lo, 4) == 0.4385 and hi == 1.0
    assert wilson(0, 0) == (0.0, 1.0)


def test_wilson_stays_inside_zero_one_and_contains_the_estimate():
    for n in (1, 5, 25, 100):
        for k in range(n + 1):
            lo, hi = wilson(k, n)
            assert 0 <= lo <= k / n <= hi <= 1


def test_mcnemar_exact_known_values():
    assert mcnemar_exact(0, 0) == 1.0
    assert mcnemar_exact(1, 1) == 1.0
    assert mcnemar_exact(5, 0) == pytest.approx(0.0625)
    assert mcnemar_exact(0, 5) == pytest.approx(0.0625)
    assert mcnemar_exact(8, 2) == pytest.approx(2 * 56 / 1024)
    assert mcnemar_exact(10, 0) == pytest.approx(2 / 1024)
    assert mcnemar_exact(3, 4) == mcnemar_exact(4, 3)


def test_bootstrap_is_seeded_and_brackets_the_mean():
    diffs = [1] * 12 + [-1] * 3 + [0] * 85
    a = paired_bootstrap(diffs, seed=1)
    assert a == paired_bootstrap(diffs, seed=1)
    assert a != paired_bootstrap(diffs, seed=2)
    assert a[0] < 0.09 < a[1]
    assert a[0] > 0  # 12 vs 3 of 100 is clear of zero


def test_bootstrap_without_any_difference_is_exactly_zero():
    assert paired_bootstrap([0] * 10, seed=3) == (0.0, 0.0)
    assert paired_bootstrap([], seed=3) == (0.0, 0.0)


def test_identical_outcomes_give_p_one_and_no_detectable_difference():
    x = [True, True, False]
    c = compare(x, list(x))
    assert c.discordant == 0 and c.p == 1.0 and c.diff == 0.0 and not c.detectable
    assert "no detectable difference" in reading(c, "D", "B")


def test_all_correct_is_handled():
    c = compare([True] * 3, [True] * 3)
    assert (c.both_right, c.both_wrong, c.p) == (3, 0, 1.0)
    assert "no detectable difference" in reading(c, "D", "B")


def test_a_difference_needs_both_the_test_and_the_interval():
    x = [True] * 20 + [False] * 80
    y = [False] * 20 + [False] * 80
    c = compare(x, y)
    assert c.detectable and "D higher than B" in reading(c, "D", "B")
    small = compare([True, True, False], [False, False, False])  # 2 vs 0 of 3, p = 0.5
    assert not small.detectable
    assert "no detectable difference" in reading(small, "D", "B")
    assert "higher" not in reading(small, "D", "B")


def test_the_winner_can_be_either_side():
    x, y = [False] * 100, [True] * 20 + [False] * 80
    assert "B higher than D" in reading(compare(x, y), "D", "B")


def test_unpaired_lengths_are_refused():
    with pytest.raises(ValueError):
        compare([True], [True, False])
