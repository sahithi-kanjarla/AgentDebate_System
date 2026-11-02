"""DebaterOutput.reasoning accepts a list of steps (seen from Mistral); nothing else is loosened."""

import pytest
from pydantic import ValidationError

from app.debate.parsing import parse_with_repair
from app.providers.base import Message
from app.providers.mock import MockProvider, MockScript, MockTurn
from app.schemas import DebaterOutput

MSGS = [Message(role="user", content="ROLE: debater\nROUND: 0")]
BASE = {"final_answer": "A", "confidence": 95}


async def parsed(reasoning, **extra) -> DebaterOutput:
    output = {**BASE, "reasoning": reasoning, **extra}
    p = MockProvider(MockScript(turns={0: MockTurn(output=output)}))
    out = await parse_with_repair(p, MSGS, DebaterOutput)
    assert out.valid and out.calls == 1 and p.calls == 1  # no repair call was needed
    return out.value


async def test_list_of_strings_is_joined_with_newlines():
    value = await parsed(["KE is half m v squared.", "The ratio is 1:8."])
    assert value.reasoning == "KE is half m v squared.\nThe ratio is 1:8."
    assert value.final_answer == "A"


async def test_list_of_step_dicts_uses_their_descriptions():
    steps = [
        {"step": 1, "description": "Write the decay law."},
        {"step": 2, "description": "Solve for t."},
    ]
    assert (await parsed(steps)).reasoning == "Write the decay law.\nSolve for t."


async def test_dict_without_a_usable_description_falls_back_to_its_text():
    value = await parsed([{"step": 1}, {"step": 2, "description": ""}, 7])
    assert value.reasoning == "{'step': 1}\n{'step': 2, 'description': ''}\n7"


async def test_a_plain_string_is_unchanged():
    text = "line one\n  line two, with  spacing"
    assert (await parsed(text)).reasoning == text


def test_an_empty_list_gives_an_empty_string():
    assert DebaterOutput(reasoning=[], final_answer="A", confidence=1).reasoning == ""


@pytest.mark.parametrize("bad", [5, None, {"description": "x"}])
def test_other_types_for_reasoning_are_still_rejected(bad):
    with pytest.raises(ValidationError):
        DebaterOutput(reasoning=bad, final_answer="A", confidence=1)


@pytest.mark.parametrize("final_answer", [["A"], {"answer": "A"}, 3, None])
def test_final_answer_is_still_strict(final_answer):
    with pytest.raises(ValidationError):
        DebaterOutput(reasoning=["a", "b"], final_answer=final_answer, confidence=1)


async def test_a_list_final_answer_still_costs_a_repair_and_is_not_joined():
    bad = {"reasoning": ["step"], "final_answer": ["A"], "confidence": 90}
    good = {**BASE, "reasoning": "r"}
    p = MockProvider(MockScript(turns={0: MockTurn(output=bad, repair_output=good)}))
    out = await parse_with_repair(p, MSGS, DebaterOutput)
    assert out.valid and out.calls == 2 and out.value.final_answer == "A"
