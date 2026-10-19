"""Question sets. A dataset is a small interface so a harder set can be added later; GSM8K is the
first implementation.

    python -m eval.datasets fetch  [--dataset gsm8k]
    python -m eval.datasets sample [--dataset gsm8k] [--seed 42]
"""

import argparse
import hashlib
import json
import os
import random
import urllib.request
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from eval import DATA_DIR
from eval.scoring import Score, parse_gold, score_number

GSM8K_URL = (
    "https://raw.githubusercontent.com/openai/grade-school-math/master/"
    "grade_school_math/data/test.jsonl"
)


class DatasetError(Exception):
    pass


@dataclass(frozen=True)
class Question:
    qid: str  # stable across runs, e.g. "gsm8k-test-17"
    text: str
    gold: str  # the dataset's own gold field, interpreted only by Dataset.score


class Dataset(ABC):
    name: ClassVar[str]
    # Appended to every question; part of the experiment, so it is recorded in the run manifest.
    prompt_suffix: ClassVar[str] = ""

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

    def prompt(self, question: Question) -> str:
        return f"{question.text}\n\n{self.prompt_suffix}" if self.prompt_suffix else question.text


class GSM8K(Dataset):
    name = "gsm8k"
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


DATASETS: dict[str, Callable[[], Dataset]] = {"gsm8k": GSM8K}


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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m eval.datasets")
    ap.add_argument("command", choices=["fetch", "sample"])
    ap.add_argument("--dataset", default="gsm8k")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args(argv)
    try:
        dataset = get_dataset(args.dataset)
        if args.command == "fetch":
            if not isinstance(dataset, GSM8K):
                raise DatasetError(f"{args.dataset} has no fetch step")
            print(f"downloaded {dataset.fetch()} questions to {dataset.path}")
            print(f"sha256 {dataset.source_sha256()}")
        else:
            order = load_order(dataset, args.seed)
            print(f"{len(order)} ids ordered with seed {args.seed}; first 5: {order[:5]}")
            print(f"stored in {order_path(dataset.name, args.seed)}")
    except (DatasetError, OSError) as e:
        print(f"error: {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
