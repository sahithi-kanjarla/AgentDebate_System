import json

import pytest

from app.debate.parsing import ParseError, extract_json, parse_with_repair
from app.providers.base import CompletionResult, LLMProvider, Message, ProviderError
from app.providers.mock import MockProvider, MockScript, MockTurn
from app.schemas import DebaterOutput

GOOD = {"reasoning": "r", "final_answer": "42", "confidence": 80}
MSGS = [Message(role="user", content="ROLE: debater\nROUND: 0")]


@pytest.mark.parametrize(
    "text",
    [
        json.dumps(GOOD),
        f"```json\n{json.dumps(GOOD)}\n```",
        f"```\n{json.dumps(GOOD)}\n```",
        f"Sure! Here is my answer:\n{json.dumps(GOOD)}\nHope that helps.",
        f"{{oops not json}} then {json.dumps(GOOD)}",
    ],
)
def test_extract_json_variants(text):
    assert extract_json(text)["final_answer"] == "42"


@pytest.mark.parametrize("text", ["", "no json here", "[1, 2, 3]", "{broken"])
def test_extract_json_failures(text):
    with pytest.raises(ParseError):
        extract_json(text)


async def test_valid_first_try_uses_one_call():
    p = MockProvider(MockScript(turns={0: MockTurn(output=GOOD)}))
    out = await parse_with_repair(p, MSGS, DebaterOutput)
    assert out.valid and out.value.final_answer == "42" and out.calls == 1 and p.calls == 1


async def test_repair_succeeds_on_second_call():
    p = MockProvider(MockScript(turns={0: MockTurn(output="{nope", repair_output=GOOD)}))
    out = await parse_with_repair(p, MSGS, DebaterOutput)
    assert out.valid and out.calls == 2


async def test_schema_violation_triggers_repair():
    bad = {**GOOD, "confidence": 150}
    p = MockProvider(MockScript(turns={0: MockTurn(output=bad, repair_output=GOOD)}))
    out = await parse_with_repair(p, MSGS, DebaterOutput)
    assert out.valid and out.calls == 2


async def test_two_failures_give_invalid_outcome_not_exception():
    p = MockProvider(MockScript(turns={0: MockTurn(output="garbage")}))
    out = await parse_with_repair(p, MSGS, DebaterOutput)
    assert not out.valid and out.value is None and out.error and out.calls == 2


class Recorder(LLMProvider):
    def __init__(self) -> None:
        self.seen: list[list[Message]] = []

    async def complete(self, messages, json_mode=True):
        self.seen.append(messages)
        return CompletionResult(text="nope", tokens_in=3, tokens_out=2, latency_ms=10)


async def test_repair_message_ends_with_fix_your_json_and_tokens_accumulate():
    rec = Recorder()
    out = await parse_with_repair(rec, MSGS, DebaterOutput)
    repair_call = rec.seen[1]
    assert repair_call[-1].role == "user" and repair_call[-1].content.endswith("FIX YOUR JSON")
    assert repair_call[-2].role == "assistant" and repair_call[-2].content == "nope"
    assert (out.tokens_in, out.tokens_out, out.latency_ms) == (6, 4, 20)


async def test_provider_error_propagates():
    p = MockProvider(MockScript(turns={0: MockTurn(error="down")}))
    with pytest.raises(ProviderError):
        await parse_with_repair(p, MSGS, DebaterOutput)
