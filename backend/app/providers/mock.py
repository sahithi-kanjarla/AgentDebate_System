"""Deterministic provider for tests and the offline demo. No network.

Prompt contract (the orchestrator's prompts must follow it):
  - some message contains ``ROLE: debater`` or ``ROLE: judge``
  - debater prompts contain ``ROUND: <n>`` (0 = independent answer)
  - peer answers appear in user messages as blocks starting ``Response <n>:`` and each block
    contains a line ``Final answer: <answer>``
  - a repair request is the last message and contains ``FIX YOUR JSON``

A script entry's critique may name its target by ``target_answer`` (the mock finds whichever
"Response N" currently holds that answer, so scripts survive per-recipient shuffling) or by a
literal ``target`` such as "Response 2".
"""

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.providers.base import CompletionResult, LLMProvider, Message, ProviderError

JUDGE = "judge"


@dataclass
class MockTurn:
    """One scripted reply. `output` is a dict (rendered to JSON) or a raw string."""

    output: dict[str, Any] | str | None = None
    repair_output: dict[str, Any] | str | None = None  # reply to a "FIX YOUR JSON" retry
    error: str | None = None  # raise ProviderError with this message instead of replying
    delay_s: float = 0.0


@dataclass
class MockScript:
    turns: dict[int | str, MockTurn] = field(default_factory=dict)  # round number, or JUDGE
    default: MockTurn | None = None  # used when a round has no entry (e.g. after early stop)


_RESPONSE_BLOCK = re.compile(r"^Response (\d+):(.*?)(?=^Response \d+:|\Z)", re.S | re.M)
_FINAL_ANSWER = re.compile(r"^Final answer:\s*(.+)$", re.M)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


class MockProvider(LLMProvider):
    def __init__(self, script: MockScript) -> None:
        self.script = script
        self.calls = 0

    async def complete(self, messages: list[Message], json_mode: bool = True) -> CompletionResult:
        self.calls += 1
        joined = "\n".join(m.content for m in messages)
        role = (re.findall(r"ROLE:\s*(debater|judge)", joined) or ["debater"])[-1]
        key: int | str = JUDGE
        if role == "debater":
            key = int((re.findall(r"ROUND:\s*(\d+)", joined) or ["0"])[-1])
        is_repair = "fix your json" in messages[-1].content.lower()

        turn = self.script.turns.get(key, self.script.default)
        if turn is None:
            raise ProviderError(f"mock has no scripted turn for {key!r}", recoverable=False)
        if turn.delay_s:
            await asyncio.sleep(turn.delay_s)
        if turn.error:
            raise ProviderError(turn.error)

        output = turn.repair_output if is_repair and turn.repair_output is not None else turn.output
        if output is None:
            raise ProviderError(f"mock turn {key!r} has no output", recoverable=False)
        text = output if isinstance(output, str) else self._render(output, messages)
        return CompletionResult(
            text=text,
            tokens_in=len(joined) // 4,
            tokens_out=len(text) // 4,
            latency_ms=int(turn.delay_s * 1000),
        )

    @staticmethod
    def _peer_labels(messages: list[Message]) -> dict[str, str]:
        """Map normalized final answer -> 'Response N' from the user messages."""
        labels: dict[str, str] = {}
        for m in messages:
            if m.role != "user":
                continue
            for num, body in _RESPONSE_BLOCK.findall(m.content):
                answer = _FINAL_ANSWER.search(body)
                if answer:
                    labels.setdefault(_norm(answer.group(1)), f"Response {num}")
        return labels

    def _render(self, output: dict[str, Any], messages: list[Message]) -> str:
        critiques = output.get("critiques")
        if not critiques:
            return json.dumps(output)
        labels = self._peer_labels(messages)
        rendered = []
        for c in critiques:
            c = dict(c)
            wanted = c.pop("target_answer", None)
            if wanted is not None:
                label = labels.get(_norm(wanted))
                if label is None:
                    continue  # nobody holds that answer from this recipient's view
                c["target"] = label
            rendered.append(c)
        return json.dumps({**output, "critiques": rendered})
