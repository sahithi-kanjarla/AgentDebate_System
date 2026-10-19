"""Scoring. Exact, never fuzzy.

A prediction is right only if it is a pure number (the app's own rule, `is_pure_number`) that
equals the gold number by value: 18, 18.0, $18 and 18.00 are equal. "18 dollars", "18." and
"eighteen" are not numbers under that rule, so they are wrong. A missing answer is wrong.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal

from app.debate.consensus import is_pure_number, normalize_answer

Status = Literal["correct", "wrong", "non_numeric", "missing"]


@dataclass(frozen=True)
class Score:
    status: Status

    @property
    def correct(self) -> bool:
        return self.status == "correct"


def parse_gold(answer_text: str) -> Decimal:
    """The number after the last '####' in a GSM8K answer (thousands commas allowed)."""
    if "####" not in answer_text:
        raise ValueError("no '####' marker in gold answer")
    raw = answer_text.rsplit("####", 1)[1].strip().replace(",", "")
    try:
        return Decimal(raw)
    except InvalidOperation as e:
        raise ValueError(f"gold answer is not a number: {raw!r}") from e


def score_number(answer: str | None, gold: Decimal) -> Score:
    """Compare a model's final answer with a numeric gold by value."""
    if answer is None:
        return Score("missing")
    if not is_pure_number(answer):
        return Score("non_numeric")
    return Score("correct" if Decimal(normalize_answer(answer)) == gold else "wrong")
