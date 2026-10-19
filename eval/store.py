"""Results on disk: one JSON file per finished question, written the moment it is done.

<run>/manifest.json     settings that must not change between sessions of one run
<run>/questions/<qid>.json
<run>/ledger.json       HTTP requests spent per UTC day per provider (budget.py)
<run>/skipped.json      questions that kept failing with a non-quota error (last session)
"""

import json
import os
from pathlib import Path
from typing import Any


def atomic_write_json(path: Path, obj: Any) -> None:
    """Write via a temp file and rename, so a crash never leaves a half-written result."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


class ManifestMismatch(Exception):
    pass


class ResultStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.questions_dir = root / "questions"
        self.manifest_path = root / "manifest.json"
        self.ledger_path = root / "ledger.json"
        self.skipped_path = root / "skipped.json"

    # --- manifest ---

    def read_manifest(self) -> dict[str, Any] | None:
        if not self.manifest_path.exists():
            return None
        return json.loads(self.manifest_path.read_text(encoding="utf-8"))

    def write_manifest(self, manifest: dict[str, Any]) -> None:
        atomic_write_json(self.manifest_path, manifest)

    def check_config(self, config: dict[str, Any], *, force: bool) -> dict[str, Any] | None:
        """Refuse to mix sessions run with different models, prompts or settings."""
        manifest = self.read_manifest()
        if manifest is None or force:
            return manifest
        old = manifest.get("config", {})
        changed = sorted(k for k in {*old, *config} if old.get(k) != config.get(k))
        if changed:
            raise ManifestMismatch(
                "this run was started with different settings (" + ", ".join(changed) + "); "
                "use a new --run name, or --force if you accept mixing them"
            )
        return manifest

    # --- questions ---

    def _path(self, qid: str) -> Path:
        return self.questions_dir / f"{qid}.json"

    def done_ids(self) -> set[str]:
        """Questions with a complete result file. Temp and unreadable files do not count."""
        done = set()
        for path in self.questions_dir.glob("*.json"):
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            done.add(path.stem)
        return done

    def save_question(self, record: dict[str, Any]) -> None:
        atomic_write_json(self._path(record["qid"]), record)

    def load_questions(self) -> list[dict[str, Any]]:
        records = []
        for qid in sorted(self.done_ids()):
            records.append(json.loads(self._path(qid).read_text(encoding="utf-8")))
        return records

    # --- skipped ---

    def write_skipped(self, skipped: dict[str, str]) -> None:
        atomic_write_json(self.skipped_path, skipped)
