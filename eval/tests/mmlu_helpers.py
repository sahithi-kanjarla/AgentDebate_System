"""MMLU-Pro-shaped test data. Nothing here touches a network."""

import hashlib
import json
from pathlib import Path

from eval import mmlupro
from eval.tests.helpers import LATEX

MMLU_CATEGORIES = ("chemistry", "physics", "engineering", "law", "economics")


def mmlu_row(i: int, category: str = "chemistry", answer: str = "A", n_options: int = 4) -> dict:
    return {
        "question_id": i,
        "question": f"QID={i} Which option is right? {LATEX}",
        "options": [f"option {chr(65 + k)} of {i}" for k in range(n_options)],
        "answer": answer,
        "category": category,
        "src": "test-src",
    }


def mmlu_rows(per_category: int = 40) -> list[dict]:
    """per_category rows in each of the five categories, with distinct ids."""
    rows = []
    for c, cat in enumerate(MMLU_CATEGORIES):
        for k in range(per_category):
            rows.append(mmlu_row(1000 * c + k, cat, "ABCD"[k % 4]))
    return rows


def write_mmlu_data(data_dir: Path, rows: list[dict]) -> str:
    """The raw file and its pin, as `python -m eval.mmlupro fetch` would leave them."""
    data_dir.mkdir(parents=True, exist_ok=True)
    raw = mmlupro.normalised_jsonl(rows)
    sha = hashlib.sha256(raw).hexdigest()
    (data_dir / mmlupro.RAW_NAME).write_bytes(raw)
    (data_dir / mmlupro.MANIFEST_NAME).write_text(
        json.dumps({"source_sha256": sha, "rows": len(rows)}), encoding="utf-8"
    )
    return sha


def write_mmlu_selection(
    data_dir: Path, sha: str, ids: dict[str, list[int]], kind: str = "screen", seed: int = 42
) -> Path:
    path = mmlupro.selection_path(kind, seed, data_dir)
    path.write_text(
        json.dumps(
            {
                "kind": kind,
                "seed": seed,
                "source_sha256": sha,
                "per_category": len(next(iter(ids.values()))),
                "categories": list(ids),
                "ids": ids,
            }
        ),
        encoding="utf-8",
    )
    return path
