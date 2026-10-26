"""MMLU-Pro (TIGER-Lab/MMLU-Pro, test split): loader, letter extraction, fixed question selections.

python -m eval.mmlupro fetch                          # download, normalise, pin the sha256
python -m eval.mmlupro select --kind holdout          # 5 categories x 12, fixed seed
python -m eval.mmlupro select --kind screen           # disjoint from the holdout and other screens
python -m eval.mmlupro check                          # re-verify pin, counts and disjointness

The raw file (eval/data/mmlupro_test.jsonl) is gitignored; the manifest (the sha256 pin) and the
selection files are committed. Nothing here talks to a model provider.
"""

import argparse
import hashlib
import inspect
import json
import os
import random
import re
import shutil
import time
import urllib.error
import urllib.request
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

from eval import DATA_DIR
from eval.datasets import Dataset, DatasetError, Question, RunProfile
from eval.scoring import Score, score_letter

DATASET_ID = "TIGER-Lab/MMLU-Pro"
ROWS_URL = (
    "https://datasets-server.huggingface.co/rows?dataset=TIGER-Lab%2FMMLU-Pro"
    "&config=default&split=test&offset={offset}&length={length}"
)
INFO_URL = "https://huggingface.co/api/datasets/TIGER-Lab/MMLU-Pro"
EXPECTED_ROWS = 12032
PAGE_ROWS = 100  # the rows API serves at most 100 rows per request
MAX_FETCH_ATTEMPTS = 8
PAGE_PAUSE_S = 1.5  # between page requests, to stay under the rows API rate limit
BACKOFF_CAP_S = 60.0  # exponential backoff on a 429 without Retry-After
RETRY_AFTER_CAP_S = 120.0
PAGES_DIR_NAME = ".mmlupro_pages"  # saved pages while a fetch is in progress (gitignored)

LETTERS = "ABCDEFGHIJ"
CATEGORIES = ("chemistry", "physics", "engineering", "law", "economics")
PER_CATEGORY = 12
HOLDOUT_SEED = 2026
SCREEN_SEED = 42

RAW_NAME = "mmlupro_test.jsonl"
MANIFEST_NAME = "mmlupro_manifest.json"
# The line sent with every question; {last} is that question's own last option letter (A to D
# for 4 options, A to J for 10), and only letters in that range are accepted as answers.
PROMPT_SUFFIX = "Answer with only the letter (A to {last}) of the correct option."

_REQUIRED = ("question_id", "question", "options", "answer", "category", "src")
# "The answer is C" style fallback; only for final_answer, and only when the letter ends it.
_ANSWER_IS = re.compile(r"(?i:answer is)\s*:?\s*\(?([A-J])\)?\s*\.?\s*$")


def letters_for(n_options: int) -> str:
    """The valid answer letters of a question with `n_options` options: "ABCD" for 4."""
    return LETTERS[: max(0, min(n_options, len(LETTERS)))]


# --- letter extraction ---


def extract_letter(text: str, n_options: int = len(LETTERS)) -> str | None:
    """The option letter in a model's final_answer, or None.

    Strip, drop one trailing period and one pair of parentheses, uppercase, accept only a letter
    that is one of the question's `n_options` options (A-D for 4, A-J for 10). If that fails, fall
    back to a trailing "answer is X" (same range). Only final_answer is ever passed in, never the
    reasoning.
    """
    valid = letters_for(n_options)
    t = text.strip()
    period = t.endswith(".")
    if period:
        t = t[:-1].rstrip()
    if t.startswith("(") and t.endswith(")"):
        t = t[1:-1].strip()
    if not period and t.endswith("."):
        t = t[:-1].rstrip()
    t = t.upper()
    if len(t) == 1 and t in valid:
        return t
    m = _ANSWER_IS.search(text.strip())
    return m.group(1) if m and m.group(1) in valid else None


def normalize_letter(text: str, n_options: int = len(LETTERS)) -> str:
    """The orchestrator's answer normaliser: the letter when there is one, else unchanged."""
    return extract_letter(text, n_options) or text


def extractor_fingerprint() -> str:
    """Hash of the answer-reading rules (letters, the fallback pattern, the functions' source), so
    a screen can record exactly which parser it ran with."""
    h = hashlib.sha256(LETTERS.encode() + _ANSWER_IS.pattern.encode())
    for fn in (letters_for, extract_letter, normalize_letter, is_letter):
        h.update(inspect.getsource(fn).encode())
    return h.hexdigest()[:16]


def is_letter(text: str, n_options: int = len(LETTERS)) -> bool:
    return len(text) == 1 and text in letters_for(n_options)


# --- download ---


def _check_row(row: Any, seen: set[int]) -> dict[str, Any]:
    """One normalised row, or DatasetError. Keeps only the fields the experiment uses."""
    if not isinstance(row, dict) or not all(k in row for k in _REQUIRED):
        raise DatasetError("a row is missing required fields (question_id, question, options, ...)")
    qid, options, answer = row["question_id"], row["options"], row["answer"]
    if not isinstance(qid, int) or isinstance(qid, bool) or qid in seen:
        raise DatasetError(f"bad or duplicate question_id {qid!r}")
    if not isinstance(row["question"], str) or not row["question"].strip():
        raise DatasetError(f"question {qid} has no text")
    if not (
        isinstance(options, list)
        and 2 <= len(options) <= len(LETTERS)
        and all(isinstance(o, str) for o in options)
    ):
        raise DatasetError(f"question {qid} has malformed options")
    if not isinstance(answer, str) or answer not in LETTERS[: len(options)]:
        raise DatasetError(
            f"question {qid} has answer {answer!r} outside its {len(options)} options"
        )
    if not isinstance(row["category"], str) or not row["category"]:
        raise DatasetError(f"question {qid} has no category")
    seen.add(qid)
    return {
        "question_id": qid,
        "question": row["question"],
        "options": options,
        "answer": answer,
        "category": row["category"],
        "src": str(row["src"]),
    }


def normalised_jsonl(rows: list[dict[str, Any]]) -> bytes:
    """The bytes that are hashed and stored: one compact, key-sorted JSON object per line."""
    lines = (json.dumps(r, sort_keys=True, ensure_ascii=False, separators=(",", ":")) for r in rows)
    return ("\n".join(lines) + "\n").encode("utf-8")


def _retry_delay(error: Exception, attempt: int) -> float:
    """Seconds to wait before retrying. A 429 honours Retry-After when it is a number of seconds
    (capped), else backs off exponentially with jitter up to about 60 s; other errors wait a
    short 1, 2, 4... s."""
    if isinstance(error, urllib.error.HTTPError) and error.code == 429:
        header = error.headers.get("Retry-After") if error.headers else None
        try:
            if header is not None:
                return min(max(float(header), 0.0), RETRY_AFTER_CAP_S)
        except ValueError:
            pass  # an HTTP date or junk: fall back to the backoff
        return min(BACKOFF_CAP_S, 5.0 * 2**attempt) * random.uniform(0.75, 1.0)
    return 2.0**attempt


def _get_json(opener: Callable[..., Any], url: str, sleep: Callable[[float], None]) -> Any:
    last: Exception | None = None
    for attempt in range(MAX_FETCH_ATTEMPTS):
        try:
            with opener(url, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (OSError, ValueError) as e:  # URLError, HTTPError, timeouts, bad JSON
            last = e
            if attempt < MAX_FETCH_ATTEMPTS - 1:
                sleep(_retry_delay(e, attempt))
    raise DatasetError(f"download failed after {MAX_FETCH_ATTEMPTS} attempts: {last}")


def _page_rows(
    page: Any, offset: int, total: int | None, seen: set[int]
) -> tuple[list[dict[str, Any]], int]:
    """The validated, normalised rows of one page and the dataset's total row count.
    Raises DatasetError for anything short or malformed; `seen` only grows when the page is good."""
    if offset == 0:
        total = page.get("num_rows_total") if isinstance(page, dict) else None
        if total != EXPECTED_ROWS:
            raise DatasetError(f"expected {EXPECTED_ROWS} rows, the server reports {total}")
    assert total is not None
    items = page.get("rows") if isinstance(page, dict) else None
    want = min(PAGE_ROWS, total - offset)
    if not isinstance(items, list) or len(items) != want:
        got = len(items) if isinstance(items, list) else "no"
        raise DatasetError(f"short page at offset {offset}: {got} rows, expected {want}")
    local = set(seen)
    rows = []
    for i, item in enumerate(items):
        if not isinstance(item, dict) or item.get("row_idx") != offset + i:
            raise DatasetError(f"row index mismatch at offset {offset + i}")
        if item.get("truncated_cells"):
            raise DatasetError(f"row {offset + i} has truncated cells; refusing it")
        rows.append(_check_row(item.get("row"), local))
    seen |= local
    return rows, total


def _cached_page(pages_dir: Path, offset: int) -> Any | None:
    path = pages_dir / f"page_{offset:06d}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    except (OSError, ValueError):
        return None  # unreadable: fetch it again


def fetch(
    data_dir: Path = DATA_DIR,
    opener: Callable[..., Any] = urllib.request.urlopen,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Download the test split page by page, validate it, write the raw file and the pin.

    Pages are paced (PAGE_PAUSE_S apart) and each good page is saved under PAGES_DIR_NAME, so a
    rerun after a failure resumes there instead of starting over. Those pages are deleted only
    after the validated file and the pin are written. Nothing else is written unless all 12,032
    rows arrive and validate. If a manifest already exists, the new download must hash to the
    same sha256, otherwise it is refused and nothing changes.
    """
    pages_dir = data_dir / PAGES_DIR_NAME
    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    total: int | None = None
    offset = 0
    fetched_any = False
    while total is None or offset < total:
        page, from_cache = _cached_page(pages_dir, offset), True
        got: tuple[list[dict[str, Any]], int] | None = None
        if page is not None:
            try:
                got = _page_rows(page, offset, total, seen)
            except DatasetError:
                got = None  # a bad saved page: fetch it again
        if got is None:
            if fetched_any:
                sleep(PAGE_PAUSE_S)
            fetched_any, from_cache = True, False
            url = ROWS_URL.format(offset=offset, length=PAGE_ROWS)
            page = _get_json(opener, url, sleep)
            got = _page_rows(page, offset, total, seen)
        page_rows, total = got
        if not from_cache:
            pages_dir.mkdir(parents=True, exist_ok=True)
            _atomic_write(pages_dir / f"page_{offset:06d}.json", json.dumps(page).encode("utf-8"))
        rows.extend(page_rows)
        offset += len(page_rows)
    if len(rows) != EXPECTED_ROWS:
        raise DatasetError(f"expected {EXPECTED_ROWS} rows, got {len(rows)}: partial download?")

    raw = normalised_jsonl(rows)
    sha = hashlib.sha256(raw).hexdigest()
    manifest_path = data_dir / MANIFEST_NAME
    if manifest_path.exists():
        pinned = json.loads(manifest_path.read_text(encoding="utf-8")).get("source_sha256")
        if pinned != sha:
            raise DatasetError(
                f"the download hashes to {sha} but {manifest_path.name} pins {pinned}: the "
                f"upstream dataset changed. Nothing was written (delete {pages_dir} to start over)."
            )
    try:
        info = _get_json(opener, INFO_URL, sleep)
        revision = info.get("sha") if isinstance(info, dict) else None
    except DatasetError:
        revision = None  # best effort; the sha256 is the pin
    manifest = {
        "dataset": DATASET_ID,
        "split": "test",
        "rows": len(rows),
        "source_sha256": sha,
        "normalisation": "keys question_id, question, options, answer, category, src; "
        "sort_keys, compact separators, ensure_ascii=False, one row per line in row_idx order",
        "revision": revision,
        "fetched": datetime.now(UTC).date().isoformat(),
    }
    data_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write(data_dir / RAW_NAME, raw)
    _atomic_write(manifest_path, (json.dumps(manifest, indent=1) + "\n").encode("utf-8"))
    shutil.rmtree(pages_dir, ignore_errors=True)  # only now: the validated file is on disk
    return manifest


def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def load_rows(data_dir: Path = DATA_DIR) -> tuple[list[dict[str, Any]], str]:
    """The validated rows and the pinned sha256. Refuses a missing, changed or short file."""
    raw_path, manifest_path = data_dir / RAW_NAME, data_dir / MANIFEST_NAME
    if not manifest_path.exists() or not raw_path.exists():
        raise DatasetError(
            f"{raw_path} or its manifest not found; run: python -m eval.mmlupro fetch"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw = raw_path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    if sha != manifest.get("source_sha256"):
        raise DatasetError(f"{raw_path.name} does not match the pin in {manifest_path.name}")
    seen: set[int] = set()
    try:
        # split on the newline character only: str.splitlines() also breaks on U+0085 and
        # U+2028, which occur unescaped inside some questions
        text = raw.decode("utf-8")
        rows = [_check_row(json.loads(line), seen) for line in text.split("\n") if line]
    except (UnicodeDecodeError, ValueError) as e:
        raise DatasetError("the stored file is not valid MMLU-Pro jsonl") from e
    if len(rows) != manifest.get("rows"):
        raise DatasetError(f"expected {manifest.get('rows')} rows, got {len(rows)}")
    return rows, sha


# --- fixed selections ---


def selection_path(kind: str, seed: int, data_dir: Path = DATA_DIR) -> Path:
    return data_dir / f"mmlupro_{kind}_seed{seed}.json"


def read_selection(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise DatasetError(f"{path} not found; run: python -m eval.mmlupro select")
    sel = json.loads(path.read_text(encoding="utf-8"))
    for cat in sel["categories"]:
        if len(sel["ids"].get(cat, [])) != sel["per_category"]:
            raise DatasetError(f"{path.name}: {cat} does not have {sel['per_category']} ids")
    return sel


def selected_ids(sel: dict[str, Any]) -> set[int]:
    return {i for ids in sel["ids"].values() for i in ids}


def all_selection_files(data_dir: Path = DATA_DIR) -> dict[str, dict[str, Any]]:
    return {p.name: read_selection(p) for p in sorted(data_dir.glob("mmlupro_*_seed*.json"))}


def assert_disjoint(selections: dict[str, dict[str, Any]]) -> None:
    """No question id appears in two selection files, and none twice inside one."""
    owner: dict[int, str] = {}
    for name, sel in selections.items():
        listed = [i for ids in sel["ids"].values() for i in ids]
        if len(listed) != len(set(listed)):
            raise DatasetError(f"{name} lists a question twice")
        for i in listed:
            if i in owner:
                raise DatasetError(f"question {i} is in both {owner[i]} and {name}")
            owner[i] = name


def draw(
    rows: list[dict[str, Any]],
    seed: int,
    exclude: set[int],
    categories: tuple[str, ...] = CATEGORIES,
    per_category: int = PER_CATEGORY,
) -> dict[str, list[int]]:
    """`per_category` ids from each category, seeded per category, never from `exclude`."""
    out: dict[str, list[int]] = {}
    for cat in categories:
        pool = sorted(r["question_id"] for r in rows if r["category"] == cat)
        pool = [i for i in pool if i not in exclude]
        if len(pool) < per_category:
            raise DatasetError(f"{cat}: only {len(pool)} questions left, need {per_category}")
        random.Random(f"{seed}:{cat}").shuffle(pool)
        out[cat] = pool[:per_category]
    return out


def select(kind: str, seed: int, data_dir: Path = DATA_DIR) -> tuple[Path, bool]:
    """Create the fixed selection file for `kind` ("holdout" or "screen") and return
    (path, created). The holdout is drawn first; a screen is drawn from what is left after the
    holdout and every other screen, so a rescreen with a new seed is disjoint by construction.
    An existing file is never overwritten: it must equal what the seed would draw today."""
    if kind not in ("holdout", "screen"):
        raise DatasetError(f"unknown selection kind {kind!r}")
    rows, sha = load_rows(data_dir)
    path = selection_path(kind, seed, data_dir)
    others = {n: s for n, s in all_selection_files(data_dir).items() if n != path.name}
    if (
        kind == "screen"
        and not any(n.startswith("mmlupro_holdout_") for n in others)
        and (not path.exists())
    ):
        raise DatasetError(
            "select the holdout first (python -m eval.mmlupro select --kind holdout)"
        )
    exclude = set().union(*(selected_ids(s) for s in others.values())) if others else set()
    sel = {
        "dataset": DATASET_ID,
        "kind": kind,
        "seed": seed,
        "source_sha256": sha,
        "per_category": PER_CATEGORY,
        "categories": list(CATEGORIES),
        "ids": draw(rows, seed, exclude),
    }
    if path.exists():
        if read_selection(path) != sel:
            raise DatasetError(f"{path.name} exists and differs from a fresh draw; not overwriting")
        assert_disjoint({**others, path.name: sel})
        return path, False
    assert_disjoint({**others, path.name: sel})
    _atomic_write(path, (json.dumps(sel, indent=1) + "\n").encode("utf-8"))
    return path, True


# --- datasets ---


class MMLUPro(Dataset):
    """A fixed subset of the MMLU-Pro test split: 5 categories x 12 questions."""

    label = "MMLU-Pro test split, chemistry/physics/engineering/law/economics (60 questions)"
    prompt_suffix = PROMPT_SUFFIX
    # Reasoning models spend output tokens before the JSON, so give each answer more room, and
    # pace Groq (its free tier limits tokens per minute and both Groq agents share the pool).
    # All three numbers are guesses until a real run shows token use and 429s.
    profile = RunProfile(max_tokens=2048, rpm={"groq": 4}, sleep_s=60.0, repair_factor=1.3)
    runs_c = False
    exploratory_tests = False
    answer_letters = True
    invalid_label = "Invalid answers (not a letter A-J)"
    kind: ClassVar[str] = "screen"
    seed: ClassVar[int] = SCREEN_SEED

    def __init__(self, data_dir: Path = DATA_DIR, selection: Path | None = None) -> None:
        self.data_dir = data_dir
        self.selection = selection or selection_path(self.kind, self.seed, data_dir)

    def load(self) -> list[Question]:
        rows, sha = load_rows(self.data_dir)
        sel = read_selection(self.selection)
        if sel["source_sha256"] != sha:
            raise DatasetError(f"{self.selection.name} was drawn from a different download")
        assert_disjoint(all_selection_files(self.data_dir))
        by_id = {r["question_id"]: r for r in rows}
        questions = []
        for cat in sel["categories"]:
            for i in sel["ids"][cat]:
                if i not in by_id:
                    raise DatasetError(f"question {i} of {self.selection.name} is not in the data")
                questions.append(self._question(by_id[i]))
        return questions

    @staticmethod
    def _question(row: dict[str, Any]) -> Question:
        options = "\n".join(f"{LETTERS[i]}. {o}" for i, o in enumerate(row["options"]))
        meta = {
            "category": row["category"],
            "src": row["src"],
            "question_id": row["question_id"],
            "n_options": len(row["options"]),
        }
        return Question(
            f"mmlupro-{row['question_id']}", f"{row['question']}\n\n{options}", row["answer"], meta
        )

    def source_sha256(self) -> str:
        return load_rows(self.data_dir)[1]

    @staticmethod
    def _options(question: Question | None) -> int:
        return question.meta["n_options"] if question else len(LETTERS)

    def suffix_for(self, question: Question) -> str:
        return PROMPT_SUFFIX.format(last=letters_for(self._options(question))[-1])

    def normalize_answer(self, answer: str, question: Question | None = None) -> str:
        return normalize_letter(answer, self._options(question))

    def is_valid_answer(self, answer: str, question: Question | None = None) -> bool:
        return is_letter(answer, self._options(question))

    def score(self, question: Question, answer: str | None) -> Score:
        n = self._options(question)
        shown = None if answer is None else normalize_letter(answer, n)
        return score_letter(shown, question.gold, lambda a: is_letter(a, n))

    def describe(self, questions: list[Question]) -> str:
        counts = Counter(q.meta["category"] for q in questions)
        by_cat = ", ".join(f"{c}: {counts[c]}" for c in CATEGORIES)
        return f"{len(questions)} questions ({by_cat})"


class MMLUProScreen(MMLUPro):
    name = "mmlupro-screen"
    kind = "screen"
    seed = SCREEN_SEED


class MMLUProHoldout(MMLUPro):
    name = "mmlupro-holdout"
    kind = "holdout"
    seed = HOLDOUT_SEED


def main(argv: list[str] | None = None, *, data_dir: Path = DATA_DIR) -> int:
    ap = argparse.ArgumentParser(prog="python -m eval.mmlupro", description=__doc__)
    ap.add_argument("command", choices=["fetch", "select", "check"])
    ap.add_argument("--kind", choices=["holdout", "screen"])
    ap.add_argument("--seed", type=int, help="default: 2026 for the holdout, 42 for a screen")
    args = ap.parse_args(argv)
    try:
        if args.command == "fetch":
            m = fetch(data_dir)
            print(f"downloaded {m['rows']} rows to {data_dir / RAW_NAME}")
            print(f"sha256 {m['source_sha256']} (revision {m['revision']})")
        elif args.command == "select":
            if not args.kind:
                raise DatasetError("select needs --kind holdout|screen")
            seed = (
                args.seed
                if args.seed is not None
                else (HOLDOUT_SEED if args.kind == "holdout" else SCREEN_SEED)
            )
            path, created = select(args.kind, seed, data_dir)
            print(f"{'wrote' if created else 'verified existing'} {path}")
        else:
            rows, sha = load_rows(data_dir)
            sels = all_selection_files(data_dir)
            assert_disjoint(sels)
            print(f"{len(rows)} rows, sha256 {sha}")
            for name, sel in sels.items():
                n = len(selected_ids(sel))
                print(f"{name}: {n} ids, pin {'ok' if sel['source_sha256'] == sha else 'MISMATCH'}")
            print("selections are pairwise disjoint")
    except (DatasetError, OSError) as e:
        print(f"error: {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
