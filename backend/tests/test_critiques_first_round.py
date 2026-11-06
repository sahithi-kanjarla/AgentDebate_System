"""A round-0 answer ignores "critiques"; every later round validates it as strictly as before.

The shapes here are real ones from Mistral ministral-8b/14b in the MMLU-Pro screens: a list of bare
strings, and dicts with their own keys instead of target/issue/severity.
"""

import json

import pytest
from pydantic import ValidationError

from app.debate.parsing import parse_with_repair
from app.providers.base import Message
from app.providers.mock import MockProvider, MockScript, MockTurn
from app.schemas import FIRST_ROUND, DebaterOutput

ROUND_0 = [Message(role="user", content="ROLE: debater\nROUND: 0")]
ROUND_1 = [Message(role="user", content="ROLE: debater\nROUND: 1")]
BASE = {"reasoning": "r", "final_answer": "A", "confidence": 95}
MALFORMED = [
    ["Option C is misleading.", "The phrasing is ambiguous."],  # list of plain strings
    [{"issue": "unit confusion", "impact": "wrong Q_gen"}],  # no target, no severity
    [{"critique": "The Nyquist rate is wrong."}],  # a key of the model's own invention
    ["a string", {"target": "Response 2", "issue": "i", "severity": "low"}],  # one of each
]
GOOD = [{"target": "Response 2", "issue": "off by a factor of ten", "severity": "high"}]


def reply(critiques, **extra) -> str:
    return json.dumps({**BASE, "critiques": critiques, **extra})


@pytest.mark.parametrize("critiques", MALFORMED)
def test_round_0_drops_malformed_critiques(critiques):
    value = DebaterOutput.model_validate({**BASE, "critiques": critiques}, context=FIRST_ROUND)
    assert value.critiques == [] and value.final_answer == "A" and value.confidence == 95


@pytest.mark.parametrize("critiques", MALFORMED)
def test_a_critique_round_still_rejects_them(critiques):
    with pytest.raises(ValidationError):
        DebaterOutput.model_validate({**BASE, "critiques": critiques})


def test_round_0_keeps_nothing_even_when_the_critique_is_well_formed():
    value = DebaterOutput.model_validate({**BASE, "critiques": GOOD}, context=FIRST_ROUND)
    assert value.critiques == []  # round 0 has no peers, so there is nothing to resolve a target to


def test_a_critique_round_keeps_a_well_formed_critique():
    value = DebaterOutput.model_validate({**BASE, "critiques": GOOD})
    assert [c.target for c in value.critiques] == ["Response 2"]
    assert value.critiques[0].severity == "high"


async def test_a_screen_style_round_0_call_needs_no_repair():
    p = MockProvider(MockScript(turns={0: MockTurn(output=reply(MALFORMED[0]))}))
    out = await parse_with_repair(p, ROUND_0, DebaterOutput, context=FIRST_ROUND)
    assert out.valid and out.calls == 1 and p.calls == 1  # the answer is scored, not lost
    assert out.value.final_answer == "A" and out.value.critiques == []


async def test_the_same_reply_in_a_critique_round_costs_a_repair_and_fails():
    p = MockProvider(MockScript(turns={1: MockTurn(output=reply(MALFORMED[0]))}))
    out = await parse_with_repair(p, ROUND_1, DebaterOutput)  # no context: strict
    assert not out.valid and out.value is None and p.calls == 2
    assert "critiques" in out.error
