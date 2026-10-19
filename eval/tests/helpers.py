"""Scripted providers and a tiny GSM8K file for the eval tests. Nothing here touches a network."""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.core.settings import AgentsFile
from app.providers.base import CompletionResult, LLMProvider, Message
from eval.datasets import GSM8K


@dataclass
class Call:
    agent_id: str
    q: int  # question number, from "QID=<n>" in the prompt
    role: str  # "debater" or "judge"
    round: int  # debater round; judge: 99
    text: str  # the whole prompt
    repair: bool

    @property
    def judge_saw_round2(self) -> bool:
        return "Critique round 2" in self.text


# A behaviour returns the final answer string, an Exception to raise, or "RAW:<text>" for a
# reply that is not valid JSON.
Behaviour = Callable[[Call], "str | Exception"]


class ScriptedProvider(LLMProvider):
    def __init__(
        self, agent_id: str, behave: Behaviour, *, fallback: Callable[[Call], bool] | None = None
    ):
        self.agent_id = agent_id
        self.behave = behave
        self.fallback = fallback
        self.calls: list[Call] = []
        self.name = "mock"
        self.model = f"mock-{agent_id}"

    async def complete(self, messages: list[Message], json_mode: bool = True) -> CompletionResult:
        joined = "\n".join(m.content for m in messages)
        role = (re.findall(r"ROLE:\s*(debater|judge)", joined) or ["debater"])[-1]
        rnd = int((re.findall(r"ROUND:\s*(\d+)", joined) or ["0"])[-1]) if role == "debater" else 99
        q = int(re.search(r"QID=(\d+)", joined).group(1))
        call = Call(
            self.agent_id, q, role, rnd, joined, "fix your json" in messages[-1].content.lower()
        )
        self.calls.append(call)
        reply = self.behave(call)
        if isinstance(reply, Exception):
            raise reply
        if reply.startswith("RAW:"):
            text = reply[4:]
        elif role == "judge":
            text = json.dumps(
                {"final_answer": reply, "confidence": 90, "summary": "s", "consensus_reached": True}
            )
        else:
            text = json.dumps({"reasoning": "r", "final_answer": reply, "confidence": 80})
        return CompletionResult(
            text=text,
            tokens_in=10,
            tokens_out=5,
            latency_ms=7,
            fallback_used=bool(self.fallback and self.fallback(call)),
        )


def factory(behave: Behaviour, **kw):
    """Provider factory for eval.run.main; keeps the providers reachable as `.made`."""

    def make(agents: AgentsFile) -> dict[str, LLMProvider]:
        make.made = {c.id: ScriptedProvider(c.id, behave, **kw) for c in agents.all_agents()}  # type: ignore[attr-defined]
        return make.made  # type: ignore[attr-defined]

    return make


def gold_of(q: int) -> int:
    return 10 + q


def write_gsm8k(path: Path, n: int = 5) -> GSM8K:
    rows = [
        {
            "question": f"QID={i} What is ten plus {i}?",
            "answer": f"10 + {i} = <<10+{i}>>\n#### {gold_of(i)}",
        }
        for i in range(n)
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return GSM8K(path)


def standard(c: Call) -> str | Exception:
    """Q0: debate fixes a wrong majority. Q1: unanimous. Q2: never agrees, three-way tie."""
    g = str(gold_of(c.q))
    wrong = str(gold_of(c.q) + 100)
    idx = int(c.agent_id.split("_")[1]) - 1 if c.role == "debater" else 0
    if c.q == 0:
        if c.role == "judge":
            return g if c.judge_saw_round2 else wrong
        table = {0: [g, wrong, wrong], 1: [g, g, wrong]}
        return table.get(c.round, [g, g, g])[idx]
    if c.q == 1:
        return g
    if c.role == "judge":
        return g
    return [g, str(gold_of(c.q) + 1), str(gold_of(c.q) + 2)][idx]


# A problem as the MATH dataset writes it: inline and display math, braces, backslashes, dollar
# signs and a literal "\n" sequence. It must reach the models exactly as written.
LATEX = (
    r"Let $f(x)=\frac{1}{2}x^{2}$ and ${a}$ with \textbf{bold} \ costs \$5, $$\sum_{i=1}^{n} i$$ "
    r"and \(x\) \n $\mathbf{v}$ in \boxed{} ${\$}$. Find the value."
)


def math_rows(overrides: dict[int, dict] | None = None, n: int = 500) -> list[dict]:
    """MATH-500 shaped rows. Row i has level i % 5 + 1 and answer 10 + i, except a non-integer
    answer on every row where i % 11 == 3. `overrides` replaces fields of single rows."""
    rows = []
    for i in range(n):
        rows.append(
            {
                "problem": f"QID={i} {LATEX}",
                "solution": "worked solution",
                "answer": r"\frac{1}{2}" if i % 11 == 3 else str(gold_of(i)),
                "subject": "Algebra" if i % 2 else "Number Theory",
                "level": i % 5 + 1,
                "unique_id": f"test/algebra/{i}.json",
            }
        )
    for i, fields in (overrides or {}).items():
        rows[i].update(fields)
    return rows


def write_math(path: Path, overrides: dict[int, dict] | None = None):
    from eval.datasets import MATH45

    path.write_text("\n".join(json.dumps(r) for r in math_rows(overrides)) + "\n", encoding="utf-8")
    return MATH45(path)


def eligible_math_indices(rows: list[dict]) -> list[int]:
    import re

    return [
        i
        for i, r in enumerate(rows)
        if str(r["level"]) in ("4", "5") and re.fullmatch(r"-?(\d{1,3}(,\d{3})+|\d+)", r["answer"])
    ]
