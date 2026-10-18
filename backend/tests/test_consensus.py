import pytest

from app.debate.consensus import ClusterIds, compute_consensus, normalize_answer


@pytest.mark.parametrize(
    "variants",
    [
        ["42", "42.0", "42.00", "$42", "$42.00", "₹42", "+42"],
        ["1,042", "1042", "$1,042.00", "1042.0"],
        ["-3.50", "-3.5"],
        [".5", "0.5"],
    ],
)
def test_pure_numbers_compare_by_value(variants):
    assert len({normalize_answer(v) for v in variants}) == 1


@pytest.mark.parametrize(
    "a,b",
    [
        ("42", "43"),
        ("42", "4.2"),
        ("100", "10"),
        ("0.5", "5"),
        ("1,2,3", "123"),  # a list, not a thousands separator
        ("1,23", "123"),
    ],
)
def test_different_numbers_stay_different(a, b):
    assert normalize_answer(a) != normalize_answer(b)


@pytest.mark.parametrize(
    "a,b",
    [
        ("[1,2]", "[1, 2]"),
        ("[1] [1,2] [1,2,3]", "[1] [1, 2] [1, 2, 3]"),
        ("hello world", "helloworld"),
        ("True", "true"),
        ("Yes", "yes"),
        ("Yes.", "Yes"),
        (" X", "X"),
        ("X ", "X"),
        ("42.", "42"),  # a trailing period is not dropped, so this is text, not a number
        (" 42", "42"),
        ("42 ", "42"),
        ("42 apples", "42"),
        ("a\n  b", "a\nb"),
        ("def f():\n    return 1", "def f():\n  return 1"),  # indentation only
        ("def f():\n    return 1\n", "def f():\n    return 1"),  # trailing newline
        ("print   X", "print X"),  # internal whitespace runs
    ],
)
def test_text_is_compared_exactly(a, b):
    assert normalize_answer(a) != normalize_answer(b)
    c = compute_consensus({"A": a, "B": b}, ClusterIds())
    assert len(c.clusters) == 2 and not c.agreed


def test_text_is_returned_untouched():
    for text in ["Paris", "  padded  ", "[1, 2]", "nan", "inf", "1e5", "Yes.", "a\tb\n"]:
        assert normalize_answer(text) == text


def test_normalized_number_values():
    assert normalize_answer("42.0") == "42"
    assert normalize_answer("$42") == "42"
    assert normalize_answer("1,042") == "1042"
    assert normalize_answer("100") == "100"  # no scientific notation
    assert normalize_answer("-3.50") == "-3.5"


def test_unanimous_across_number_spellings():
    c = compute_consensus({"A": "42", "B": "42.0", "C": "$42"}, ClusterIds())
    assert c.agreed and c.score == 1.0 and len(c.clusters) == 1
    assert c.clusters[0].agents == ["A", "B", "C"]


def test_identical_text_clusters_and_near_misses_do_not():
    c = compute_consensus({"A": "Yes", "B": "Yes", "C": "yes"}, ClusterIds())
    assert not c.agreed and c.score == pytest.approx(2 / 3)
    assert [sorted(cl.agents) for cl in c.clusters] == [["A", "B"], ["C"]]


def test_the_mutable_default_argument_case_from_a_real_debate():
    same = "[1] [1, 2] [1, 2, 3]"
    c = compute_consensus({"A": same, "B": "[1] [1,2] [1,2,3]", "C": same}, ClusterIds())
    assert not c.agreed and [sorted(cl.agents) for cl in c.clusters] == [["A", "C"], ["B"]]


def test_all_different():
    c = compute_consensus({"A": "1", "B": "2", "C": "3"}, ClusterIds())
    assert not c.agreed and c.score == pytest.approx(1 / 3) and len(c.clusters) == 3


def test_invalid_agent_counts_in_denominator_but_cannot_agree():
    c = compute_consensus({"A": "7", "B": "7", "C": None}, ClusterIds())
    assert c.agreed and c.score == pytest.approx(2 / 3)


def test_single_valid_answer_is_not_agreement():
    c = compute_consensus({"A": "7", "B": None, "C": None}, ClusterIds())
    assert not c.agreed


def test_no_valid_answers():
    c = compute_consensus({"A": None, "B": None}, ClusterIds())
    assert not c.agreed and c.score == 0.0 and c.clusters == []


def test_cluster_ids_are_stable_across_rounds():
    ids = ClusterIds()
    r0 = compute_consensus({"A": "408", "B": "408", "C": "398"}, ids)
    r1 = compute_consensus({"A": "408", "B": "408", "C": "408.0"}, ids)
    assert {c.normalized_answer: c.cluster_id for c in r0.clusters} == {"408": 0, "398": 1}
    assert [c.cluster_id for c in r1.clusters] == [0]
