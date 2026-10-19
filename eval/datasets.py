"""Question sets behind a small interface: GSM8K, and MATH-500 levels 4-5 (integer answers).

python -m eval.datasets fetch  [--dataset gsm8k|math45]
python -m eval.datasets sample [--dataset gsm8k|math45] [--seed 42]
"""

import argparse
import hashlib
import json
import os
import random
import re
import urllib.request
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, ClassVar

from eval import DATA_DIR
from eval.budget import DEFAULT_SLEEP_BETWEEN_S
from eval.scoring import Score, parse_gold, score_number

GSM8K_URL = (
    "https://raw.githubusercontent.com/openai/grade-school-math/master/"
    "grade_school_math/data/test.jsonl"
)


# The plain raw.githubusercontent.com URL for this file returns a git-lfs pointer, not the data.
MATH500_URL = (
    "https://media.githubusercontent.com/media/openai/prm800k/main/prm800k/math_splits/test.jsonl"
)
MATH500_ROWS = 500
LFS_POINTER = b"version https://git-lfs"
# A plain integer: optional minus sign, digits, thousands commas only in proper groups of three.
_INTEGER = re.compile(r"-?(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)")


class DatasetError(Exception):
    pass


@dataclass(frozen=True)
class RunProfile:
    """How a dataset should be run. Applied only to the eval's own copy of the agent config
    (never to agents.yaml, so the app is unaffected); empty/None means "use the app's values"."""

    max_tokens: int | None = None  # raise every agent's output limit to at least this
    rpm: dict[str, float] = field(default_factory=dict)  # per-provider requests per minute
    sleep_s: float = DEFAULT_SLEEP_BETWEEN_S  # pause after a question that sent requests
    repair_factor: float = 1.0  # expected extra calls from repair retries, for the estimate

    @property
    def is_default(self) -> bool:
        return self.max_tokens is None and not self.rpm


@dataclass(frozen=True)
class Question:
    qid: str  # stable across runs, e.g. "gsm8k-test-17"
    text: str
    gold: str  # the dataset's own gold field, interpreted only by Dataset.score
    meta: dict[str, Any] = field(default_factory=dict)  # e.g. level and subject, for the record


class Dataset(ABC):
    name: ClassVar[str]
    # Appended to every question; part of the experiment, so it is recorded in the run manifest.
    prompt_suffix: ClassVar[str] = ""
    label: ClassVar[str] = ""  # human name used in the report
    profile: ClassVar[RunProfile] = RunProfile()

    @abstractmethod
    def load(self) -> list[Question]:
        """All questions in source order. Raises DatasetError if the data is not there."""

    @abstractmethod
    def source_sha256(self) -> str:
        """Hash of the underlying data, recorded so a changed file is noticed."""

    @abstractmethod
    def score(self, question: Question, answer: str | None) -> Score:
        """Exact scoring of a model's final answer; a missing or invalid answer is wrong."""

    def gold_label(self, question: Question) -> str:
        """The gold answer as shown in progress lines and result files."""
        return question.gold

    def describe(self, questions: list[Question]) -> str:
        """One line for `sample`: how many questions are eligible."""
        return f"{len(questions)} questions"

    def prompt(self, question: Question) -> str:
        """The question text exactly as the dataset has it (LaTeX included) plus the suffix."""
        return f"{question.text}\n\n{self.prompt_suffix}" if self.prompt_suffix else question.text


class GSM8K(Dataset):
    name = "gsm8k"
    label = "GSM8K (test split)"
    prompt_suffix = "Give the final answer as a plain number with no units."

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DATA_DIR / "gsm8k_test.jsonl"

    def fetch(self, opener: Callable[..., Any] = urllib.request.urlopen) -> int:
        """Download the original test split (MIT licensed) with the standard library only."""
        with opener(GSM8K_URL, timeout=60) as resp:
            raw = resp.read()
        rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
        if not rows or not all("question" in r and "answer" in r for r in rows):
            raise DatasetError("downloaded file is not GSM8K jsonl (question/answer rows)")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_bytes(raw)
        os.replace(tmp, self.path)
        return len(rows)

    def _require(self) -> None:
        if not self.path.exists():
            raise DatasetError(f"{self.path} not found; run: python -m eval.datasets fetch")

    def load(self) -> list[Question]:
        self._require()
        questions = []
        for i, line in enumerate(self.path.read_text(encoding="utf-8").splitlines()):
            if line.strip():
                row = json.loads(line)
                questions.append(Question(f"gsm8k-test-{i}", row["question"], row["answer"]))
        return questions

    def source_sha256(self) -> str:
        self._require()
        return hashlib.sha256(self.path.read_bytes()).hexdigest()

    def score(self, question: Question, answer: str | None) -> Score:
        return score_number(answer, parse_gold(question.gold))

    def gold_label(self, question: Question) -> str:
        return str(parse_gold(question.gold))


class MATH45(Dataset):
    """MATH-500 (the PRM800K test split), levels 4 and 5, rows whose answer is a plain integer."""

    name = "math45"
    label = "MATH-500 test split, levels 4-5, integer answers only"
    prompt_suffix = "Give the final answer as a plain integer with no units."
    # Harder problems mean longer reasoning: more room per answer, Groq paced by requests per
    # minute (its free tier limits tokens per minute), a longer pause between questions, and an
    # allowance for repair calls after cut-off output.
    profile = RunProfile(max_tokens=4096, rpm={"groq": 2}, sleep_s=120.0, repair_factor=1.3)

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DATA_DIR / "math500_test.jsonl"

    def fetch(self, opener: Callable[..., Any] = urllib.request.urlopen) -> int:
        with opener(MATH500_URL, timeout=120) as resp:
            raw = resp.read()
        rows = self._parse(raw)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_bytes(raw)
        os.replace(tmp, self.path)
        return len(rows)

    @staticmethod
    def _parse(raw: bytes) -> list[dict[str, Any]]:
        if raw.lstrip().startswith(LFS_POINTER):
            raise DatasetError(
                "the download is a git-lfs pointer, not the data (the URL must be on "
                "media.githubusercontent.com, not raw.githubusercontent.com)"
            )
        try:
            rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
        except (UnicodeDecodeError, ValueError) as e:
            raise DatasetError("downloaded file is not MATH-500 jsonl") from e
        needed = {"problem", "answer", "level", "subject", "unique_id"}
        if not all(isinstance(r, dict) and needed <= r.keys() for r in rows):
            raise DatasetError("downloaded file is not MATH-500 jsonl (missing fields)")
        if len(rows) != MATH500_ROWS:
            raise DatasetError(f"expected {MATH500_ROWS} rows, got {len(rows)}: partial download?")
        return rows

    def _require(self) -> None:
        if not self.path.exists():
            raise DatasetError(
                f"{self.path} not found; run: python -m eval.datasets fetch --dataset math45"
            )

    def load(self) -> list[Question]:
        """Eligible questions in source order. The id is the row's line index in the file."""
        self._require()
        out = []
        for i, row in enumerate(self._parse(self.path.read_bytes())):
            answer, level = str(row["answer"]).strip(), str(row["level"]).strip()
            if level in ("4", "5") and _INTEGER.fullmatch(answer):
                meta = {
                    "level": int(level),
                    "subject": row["subject"],
                    "unique_id": row["unique_id"],
                }
                out.append(Question(f"math500-{i}", row["problem"], answer, meta))
        return out

    def source_sha256(self) -> str:
        self._require()
        return hashlib.sha256(self.path.read_bytes()).hexdigest()

    def score(self, question: Question, answer: str | None) -> Score:
        return score_number(answer, Decimal(self.gold_label(question)))

    def gold_label(self, question: Question) -> str:
        return question.gold.replace(",", "")

    def describe(self, questions: list[Question]) -> str:
        by_level = {lv: sum(q.meta["level"] == lv for q in questions) for lv in (4, 5)}
        return (
            f"{len(questions)} eligible questions (level 4: {by_level[4]}, level 5: {by_level[5]}; "
            "integer answers only) out of the 500 in MATH-500"
        )


DATASETS: dict[str, Callable[[], Dataset]] = {"gsm8k": GSM8K, "math45": MATH45}


def get_dataset(name: str) -> Dataset:
    if name not in DATASETS:
        raise DatasetError(f"unknown dataset {name!r} (known: {', '.join(DATASETS)})")
    return DATASETS[name]()


def order_path(name: str, seed: int, data_dir: Path = DATA_DIR) -> Path:
    return data_dir / f"{name}_ids_seed{seed}.json"


def load_order(dataset: Dataset, seed: int, data_dir: Path = DATA_DIR) -> list[str]:
    """The seeded question order, created once and stored. Taking the first n of it means a
    small pilot is a prefix of a larger run, so its results are reused."""
    questions = dataset.load()
    ids = [q.qid for q in questions]
    sha = dataset.source_sha256()
    path = order_path(dataset.name, seed, data_dir)
    if path.exists():
        stored = json.loads(path.read_text(encoding="utf-8"))
        if stored.get("source_sha256") != sha or sorted(stored.get("order", [])) != sorted(ids):
            raise DatasetError(f"{path} does not match the current data; delete it to resample")
        return list(stored["order"])
    order = list(ids)
    random.Random(seed).shuffle(order)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"dataset": dataset.name, "seed": seed, "source_sha256": sha, "order": order}, indent=0
        ),
        encoding="utf-8",
    )
    return order


def main(argv: list[str] | None = None, *, data_dir: Path = DATA_DIR) -> int:
    ap = argparse.ArgumentParser(prog="python -m eval.datasets")
    ap.add_argument("command", choices=["fetch", "sample"])
    ap.add_argument("--dataset", default="gsm8k")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args(argv)
    try:
        dataset = get_dataset(args.dataset)
        if args.command == "fetch":
            if not isinstance(dataset, GSM8K | MATH45):
                raise DatasetError(f"{args.dataset} has no fetch step")
            print(f"downloaded {dataset.fetch()} rows to {dataset.path}")
            print(f"sha256 {dataset.source_sha256()}")
            print(dataset.describe(dataset.load()))
        else:
            print(dataset.describe(dataset.load()))
            order = load_order(dataset, args.seed, data_dir)
            print(f"{len(order)} ids ordered with seed {args.seed}; first 5: {order[:5]}")
            print(f"stored in {order_path(dataset.name, args.seed, data_dir)}")
    except (DatasetError, OSError) as e:
        print(f"error: {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
