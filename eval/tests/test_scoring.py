from decimal import Decimal

import pytest

from eval.scoring import parse_gold, score_number


@pytest.mark.parametrize(
    "text,expected",
    [
        ("so 5 + 13 = 18\n#### 18", "18"),
        ("steps\n#### 1,018", "1018"),
        ("a #### 3 b\n#### 7.50", "7.50"),
        ("neg\n#### -4", "-4"),
    ],
)
def test_parse_gold(text, expected):
    assert parse_gold(text) == Decimal(expected)


@pytest.mark.parametrize("text", ["no marker 18", "#### eighteen", "####"])
def test_parse_gold_rejects(text):
    with pytest.raises(ValueError):
        parse_gold(text)


@pytest.mark.parametrize("answer", ["18", "18.0", "$18", "18.00", "+18"])
def test_numbers_equal_by_value(answer):
    assert score_number(answer, Decimal(18)).correct


def test_thousands_commas_match_plain_digits():
    assert score_number("1,018", Decimal(1018)).correct
    assert score_number("$1,018.00", Decimal(1018)).correct
    assert score_number("1,18", Decimal(118)).status == "non_numeric"  # bad grouping is text


@pytest.mark.parametrize(
    "answer", ["18 dollars", "18.", " 18", "eighteen", "1e1", "nan", "", "[18]"]
)
def test_not_a_pure_number_is_wrong_without_fuzzy_matching(answer):
    s = score_number(answer, Decimal(18))
    assert s.status == "non_numeric" and not s.correct


def test_wrong_number_and_missing():
    assert score_number("19", Decimal(18)).status == "wrong"
    assert score_number(None, Decimal(18)).status == "missing"
    assert not score_number(None, Decimal(18)).correct
