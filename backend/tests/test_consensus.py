import pytest

from app.debate.consensus import ClusterIds, compute_consensus, normalize_answer


@pytest.mark.parametrize(
    "variants",
    [
        ["42", "42.0", "$42", " 42 ", "42.", "42.00", "$42.00", "₹42"],
        ["Yes.", "yes", "YES", " Yes! ", '"Yes"'],
        ["1,042", "1042", "$1,042.00"],
        ["No", "no."],
    ],
)
def test_variants_normalize_identically(variants):
    assert len({normalize_answer(v) for v in variants}) == 1


@pytest.mark.parametrize(
    "a,b", [("42", "43"), ("42", "4.2"), ("yes", "no"), ("100", "10"), ("0.5", "5")]
)
def test_different_answers_stay_different(a, b):
    assert normalize_answer(a) != normalize_answer(b)


def test_normalized_values():
    assert normalize_answer("42.0") == "42"
    assert normalize_answer("$42") == "42"
    assert normalize_answer("Yes.") == "yes"
    assert normalize_answer("100") == "100"  # no scientific notation
    assert normalize_answer("-3.50") == "-3.5"
    assert normalize_answer("Paris") == "paris"
    assert normalize_answer("nan") == "nan"  # text, not a number


def test_unanimous_across_spellings():
    c = compute_consensus({"A": "42", "B": "42.0", "C": "$42"}, ClusterIds())
    assert c.agreed and c.score == 1.0 and len(c.clusters) == 1
    assert c.clusters[0].agents == ["A", "B", "C"]


def test_yes_variants_cluster_together():
    c = compute_consensus({"A": "Yes.", "B": "yes", "C": "No"}, ClusterIds())
    assert not c.agreed and c.score == pytest.approx(2 / 3)
    assert [sorted(cl.agents) for cl in c.clusters] == [["A", "B"], ["C"]]


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
