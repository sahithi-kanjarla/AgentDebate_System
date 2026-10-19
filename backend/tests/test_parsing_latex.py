"""LaTeX inside JSON strings: strict parse first, escape illegal backslashes only as a fallback."""

import json

import pytest

from app.debate.parsing import (
    ParseError,
    escape_illegal_backslashes,
    extract_json,
    parse_model,
    parse_with_repair,
)
from app.providers.base import CompletionResult, LLMProvider, Message
from app.providers.mock import MockProvider, MockScript, MockTurn
from app.schemas import DebaterOutput

BS = chr(92)  # one backslash; avoids counting escapes in the literals below
MSGS = [Message(role="user", content="ROLE: debater\nROUND: 0")]


def tex(s: str) -> str:
    """Write LaTeX with `@` standing for one backslash."""
    return s.replace("@", BS)


# \frac is a legal JSON escape (form feed) but \sqrt, \left, \( and \lfloor are not.
LATEX = tex(
    '{"reasoning": "Since $z + @frac{1}{z} = @frac{1 + @sqrt{5}}{2}$ and $@left(a@right)$, '
    'see @(x@) and @lfloor y @rfloor.", "final_answer": "-2", "confidence": 90}'
)


def test_latex_with_illegal_escapes_parses_via_fallback():
    out = parse_model(LATEX, DebaterOutput)
    assert out.final_answer == "-2" and out.confidence == 90
    for piece in ("@sqrt{5}", "@left(a", "@(x", "@lfloor"):
        assert tex(piece) in out.reasoning  # the backslashes survive as literal text


def test_latex_inside_a_code_fence_and_prose():
    text = f"Here you go:\n```json\n{LATEX}\n```\nDone."
    assert extract_json(text)["final_answer"] == "-2"


def test_already_valid_json_is_returned_unchanged():
    # An escaped backslash, \n, é and \" are all legal: the strict pass keeps them as is.
    text = tex('{"a": "x @@sqrt y@n@u00e9 @" q", "b": 1}')
    assert extract_json(text) == json.loads(text)
    assert escape_illegal_backslashes(text) == text


def test_inputs_that_already_parse_keep_their_old_result():
    # \frac parses strictly (as a form feed), so the fallback never touches it.
    text = tex('{"reasoning": "@frac", "final_answer": "1", "confidence": 5}')
    assert extract_json(text)["reasoning"] == "\x0crac"


def test_escape_helper_cases():
    assert escape_illegal_backslashes(tex("@@sqrt")) == tex("@@sqrt")  # pair left alone
    assert escape_illegal_backslashes(tex("@sqrt")) == tex("@@sqrt")
    assert escape_illegal_backslashes(tex("@u00e9")) == tex("@u00e9")
    assert escape_illegal_backslashes(tex("@uZZZZ")) == tex("@@uZZZZ")  # not a real \u escape
    assert escape_illegal_backslashes(tex("end@")) == tex("end@@")  # lone trailing backslash
    assert escape_illegal_backslashes("plain text") == "plain text"


def test_still_broken_json_still_fails_after_the_fallback():
    truncated = tex('{"reasoning": "uses @sqrt", "final_answer": "1", "confidence": 5')
    with pytest.raises(ParseError):
        extract_json(truncated)
    with pytest.raises(ParseError):
        extract_json(tex("no braces, only @sqrt{5} here"))


async def test_latex_reply_needs_no_repair_call():
    p = MockProvider(MockScript(turns={0: MockTurn(output=LATEX)}))
    out = await parse_with_repair(p, MSGS, DebaterOutput)
    assert out.valid and out.calls == 1 and not out.repair_used and p.calls == 1


async def test_repair_used_and_finish_reason_are_reported():
    class Stops(LLMProvider):
        async def complete(self, messages, json_mode=True):
            return CompletionResult(
                text="nope", tokens_in=1, tokens_out=1, latency_ms=1, finish_reason="length"
            )

    out = await parse_with_repair(Stops(), MSGS, DebaterOutput)
    assert not out.valid and out.repair_used and out.finish_reason == "length"
