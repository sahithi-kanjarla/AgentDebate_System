"""Real worked examples for the landing page, taken from the MMLU-Pro holdout run.

    python -m eval.landing_examples                # writes frontend/public/examples.json

Read-only on the results folder. The landing page shows these as "real runs", so two rules keep it
honest:

* An example qualifies only if the debate's final answer was correct while at least two of the three
  debaters were wrong in round 0 (the rule is checked in code and in a test, not by eye).
* The selection is described on the page as a selection. It is not a sample, and the page links to
  the results page, which also covers the questions where debate did not help.

No model or provider is written: only debater numbers and personas (which every debate screen
already shows), answers, confidences and the judge's own summary.
"""

import json
import re
import sys
from pathlib import Path
from typing import Any

from eval import RESULTS_DIR

RUN = "mmlupro-holdout-s42"
OUTPUT = Path(__file__).resolve().parents[1] / "frontend" / "public" / "examples.json"
FORMAT = 1

SELECTION = (
    "Chosen from the test questions where debate's final answer was right and at least two of "
    "the three debaters were wrong in round 0. Not a random sample."
)

# In display order. Each must pass `qualifies`; the order mixes subjects and keeps the questions
# readable without specialist knowledge.
PICKS = ("mmlupro-7422", "mmlupro-3957", "mmlupro-1056", "mmlupro-1597")

_OPTION = re.compile(r"^([A-J])\.\s+(.*)$")


def _debater_turns(doc: dict[str, Any]) -> list[dict[str, Any]]:
    return [t for t in doc["turns"] if str(t["label"]).startswith("Debater")]


def round0_correct(doc: dict[str, Any]) -> int:
    return sum(1 for t in _debater_turns(doc) if t["round"] == 0 and t["answer"] == doc["gold"])


def qualifies(doc: dict[str, Any]) -> bool:
    debaters = [t for t in _debater_turns(doc) if t["round"] == 0]
    wrong = sum(1 for t in debaters if t["answer"] != doc["gold"])
    return bool(doc["conditions"]["D"]["correct"]) and wrong >= 2


def split_question(text: str) -> tuple[str, list[dict[str, str]]]:
    stem: list[str] = []
    options: list[dict[str, str]] = []
    for line in text.splitlines():
        m = _OPTION.match(line.strip())
        if m:
            options.append({"letter": m.group(1), "text": m.group(2)})
        elif not options:
            stem.append(line)
    return "\n".join(stem).strip(), options


def judge_summary(doc: dict[str, Any]) -> str | None:
    """The judge's own summary, only when the stored reply is complete JSON (a stored tail)."""
    judge = doc.get("judge_d") or {}
    try:
        value = json.loads(judge.get("raw_tail") or "")
    except ValueError:
        return None
    summary = value.get("summary") if isinstance(value, dict) else None
    return summary.strip() if isinstance(summary, str) and summary.strip() else None


def build_example(doc: dict[str, Any]) -> dict[str, Any]:
    stem, options = split_question(doc["question"])
    by_round: dict[int, dict[int, dict[str, Any]]] = {}
    for t in _debater_turns(doc):
        number = int(str(t["label"]).rsplit(" ", 1)[-1])
        by_round.setdefault(int(t["round"]), {})[number] = {
            "debater": number,
            "answer": t["answer"] if t.get("valid") else None,
            "confidence": t.get("confidence") if t.get("valid") else None,
        }
    rounds = [
        {"round": r, "answers": [by_round[r][n] for n in sorted(by_round[r])]}
        for r in sorted(by_round)
    ]
    judge = doc["judge_d"]
    personas = {
        int(str(t["label"]).rsplit(" ", 1)[-1]): t["persona"]
        for t in _debater_turns(doc)
        if t.get("persona")
    }
    return {
        "id": doc["qid"],
        "category": str(doc["meta"]["category"]).capitalize(),
        "stem": stem,
        "options": options,
        "gold": doc["gold"],
        "debaters": [{"debater": n, "persona": personas[n]} for n in sorted(personas)],
        "round0_correct": round0_correct(doc),
        "rounds": rounds,
        "final": {
            "answer": judge["answer"],
            "confidence": judge.get("confidence"),
            "summary": judge_summary(doc),
        },
    }


def build(results_dir: Path = RESULTS_DIR, picks: tuple[str, ...] = PICKS) -> dict[str, Any]:
    folder = results_dir / RUN / "questions"
    examples = []
    for qid in picks:
        doc = json.loads((folder / f"{qid}.json").read_text(encoding="utf-8"))
        if not qualifies(doc):
            raise ValueError(f"{qid} does not meet the selection rule")
        examples.append(build_example(doc))
    return {"format": FORMAT, "source": RUN, "selection": SELECTION, "examples": examples}


def render(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else OUTPUT
    out.write_text(render(build()), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
