import json
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from app.providers.base import LLMProvider, Message

# Must end with "FIX YOUR JSON": the mock provider keys its repair reply on it.
REPAIR_TEMPLATE = (
    "Your previous reply could not be used ({error}). Reply again with ONLY the corrected "
    "JSON object in the required shape, with no prose and no code fences. FIX YOUR JSON"
)

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S | re.I)


class ParseError(ValueError):
    pass


@dataclass
class Attempt:
    """What one provider call returned, kept for every call of a turn (first reply and repair)."""

    finish_reason: str | None  # None for cached replays and providers that report none
    tokens_out: int
    unbalanced: bool  # the reply opened more braces than it closed


@dataclass
class ParseOutcome[T: BaseModel]:
    value: T | None
    raw_text: str
    error: str | None  # why the final attempt failed; None when value is set
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    calls: int = 0
    api_calls: int = 0  # HTTP requests actually sent (retries count, cache hits do not)
    cache_hits: int = 0
    provider: str = ""  # who answered the last call
    model: str = ""
    fallback_used: bool = False
    finish_reason: str | None = None  # of the last call; None for cached replays
    attempts: list[Attempt] = field(default_factory=list)

    @property
    def repair_used(self) -> bool:
        return self.calls > 1

    @property
    def valid(self) -> bool:
        return self.value is not None


_VALID_ESCAPE_NEXT = frozenset('"\\/bfnrtu')


def escape_illegal_backslashes(text: str) -> str:
    """Double every backslash that does not start a legal JSON escape (``\\sqrt``, ``\\(``).

    Models answering maths write LaTeX inside the JSON strings without escaping it. Backslash
    pairs are consumed together, so an already escaped ``\\\\sqrt`` is left alone. ``\\u`` counts
    as legal only when four hex digits follow.
    """
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch != "\\":
            out.append(ch)
            i += 1
            continue
        nxt = text[i + 1] if i + 1 < n else ""
        legal = nxt in _VALID_ESCAPE_NEXT
        if nxt == "u":
            legal = len(text) >= i + 6 and all(
                c in "0123456789abcdefABCDEF" for c in text[i + 2 : i + 6]
            )
        if legal:
            out.append(ch + nxt)
            i += 2
        else:
            out.append("\\\\")
            i += 1
    return "".join(out)


def _first_object(candidates: list[str]) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    for candidate in candidates:
        start = candidate.find("{")
        while start != -1:
            try:
                obj, _ = decoder.raw_decode(candidate[start:])
            except json.JSONDecodeError:
                start = candidate.find("{", start + 1)
                continue
            if isinstance(obj, dict):
                return obj
            start = candidate.find("{", start + 1)
    return None


def extract_json(text: str) -> dict[str, Any]:
    """Pull the first JSON object out of a model reply (tolerates code fences and prose).

    A strict pass runs first, so anything that already parses gives the same result as before.
    Only when it finds nothing, a second pass retries after escaping illegal backslash sequences
    (LaTeX such as ``\\sqrt`` or ``\\(`` inside a string).
    """
    candidates = [m.group(1) for m in _FENCE.finditer(text)] + [text]
    obj = _first_object(candidates)
    if obj is None:
        obj = _first_object([escape_illegal_backslashes(c) for c in candidates])
    if obj is None:
        raise ParseError("no JSON object found")
    return obj


def parse_model[T: BaseModel](text: str, model: type[T]) -> T:
    try:
        return model.model_validate(extract_json(text))
    except ValidationError as e:
        fields = ", ".join(".".join(map(str, err["loc"])) or "?" for err in e.errors())
        raise ParseError(f"schema validation failed on: {fields}") from e


async def parse_with_repair[T: BaseModel](
    provider: LLMProvider,
    messages: list[Message],
    model: type[T],
    json_mode: bool = True,
) -> ParseOutcome[T]:
    """Call the provider, parse into `model`, and retry once with a repair message on failure.

    A second failure yields an invalid outcome (value=None) rather than raising, so one badly
    behaved agent never crashes the debate. ProviderError from the provider itself propagates.
    """
    outcome = ParseOutcome[T](value=None, raw_text="", error=None)
    convo = list(messages)
    for attempt in range(2):
        result = await provider.complete(convo, json_mode)
        outcome.calls += 1
        outcome.tokens_in += result.tokens_in
        outcome.tokens_out += result.tokens_out
        outcome.latency_ms += result.latency_ms
        outcome.api_calls += 0 if result.cached else result.attempts
        outcome.cache_hits += int(result.cached)
        outcome.provider = result.provider or outcome.provider
        outcome.model = result.model or outcome.model
        outcome.fallback_used = outcome.fallback_used or result.fallback_used
        outcome.raw_text = result.text
        outcome.finish_reason = result.finish_reason
        outcome.attempts.append(
            Attempt(
                result.finish_reason,
                result.tokens_out,
                result.text.count("{") > result.text.count("}"),
            )
        )
        try:
            outcome.value = parse_model(result.text, model)
            outcome.error = None
            return outcome
        except ParseError as e:
            outcome.error = str(e)
            if attempt == 0:
                convo = [
                    *convo,
                    Message(role="assistant", content=result.text),
                    Message(role="user", content=REPAIR_TEMPLATE.format(error=e)),
                ]
    return outcome
