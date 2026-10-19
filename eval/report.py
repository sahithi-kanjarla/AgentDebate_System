# ruff: noqa: E501  (the limitations text is prose kept on one line per bullet)
"""Markdown report, generated only from the per-question result files (no hand-edited numbers).

    python -m eval.report                    # print the markdown
    python -m eval.report --write-readme     # also rewrite README.md between the markers

Read-only on the results folder, so it is safe to run while a pilot is still writing.
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from eval import EVAL_DIR, RESULTS_DIR
from eval.datasets import DATASETS
from eval.stats import Comparison, compare, reading, wilson
from eval.store import ResultStore

START_MARKER = "<!-- EVAL_START -->"
END_MARKER = "<!-- EVAL_END -->"
README_PATH = EVAL_DIR.parent / "README.md"

CEILING = 0.95
SMALL_N = 30
DEBATE_ROWS = ["B", "C", "D", "D_vote"]
ALL_ROWS = ["A1", "A2", "A3", *DEBATE_ROWS]
ROW_LABELS = {
    "A1": "A1 single model (Debater 1)",
    "A2": "A2 single model (Debater 2)",
    "A3": "A3 single model (Debater 3)",
    "B": "B majority vote of the 3 round-0 answers",
    "C": "C debate, 1 critique round (judge)",
    "D": "D debate, up to 3 critique rounds (judge)",
    "D_vote": "D-vote final-round plurality (no judge, diagnostic)",
}
SHORT = {"A1": "A1", "A2": "A2", "A3": "A3", "B": "B", "C": "C", "D": "D", "D_vote": "D-vote"}

SMALL_SAMPLE = '- **Small sample.** Intervals are wide at this n; a real but modest difference between conditions would not be detected. "No detectable difference" is not evidence of no difference.'
FREE_TIER = "- **Free-tier models change.** The models, quotas and behaviour behind the free tiers shift over time. The run records the agent/prompt fingerprint and dates; a different day or lineup is a different experiment."
FALLBACKS = "- **Fallback models.** Fallbacks are off by default, so answers come from the primary models. The tables show how many answers came from fallback models and the primary-only accuracy beside the all-answers accuracy. If any answers did come from fallbacks, treat the primary-only column as the cleaner comparison."
JUDGE = "- **Judge asymmetry.** Conditions C and D include a judge model that A and B do not have; the D-vote row (final-round plurality, no judge) separates debate from the judge."
EARLY_STOP = '- **Early stopping.** D is "up to 3 rounds": it stops once all debaters agree after at least one critique round, so its cost is below a fixed 3 rounds and C equals D on those questions.'
ONE_SAMPLE = "- **One sample per question.** Models run at temperature 0.6 and each question is answered once, so run-to-run sampling noise is not measured; the intervals cover which questions were drawn, not sampling variance."
COSTS = "- **Costs.** HTTP calls exclude response-cache hits, so a question re-run after an interruption can show lower cost. Latency includes provider rate-limit waits. Repair calls are not separable per single-model answer, so A's calls are nominal (1)."

CONTAMINATION = {
    "gsm8k": (
        "GSM8K is public and very probably in the training data of these models, so accuracy "
        "here says little about unseen problems and is likely inflated."
    ),
    "math45": (
        "MATH, including its MATH-500 split, is public and very likely in the training data of "
        "these models, so accuracy here says little about unseen problems and is likely inflated."
    ),
}
MATH_EXTRA = [
    "- **Small subset.** Only level 4 and 5 problems with a plain-integer answer are used, and only a small seeded sample of those; the numbers describe that sample, not MATH as a whole.",
    "- **Integer-only filter.** Dropping every problem whose answer is a fraction, expression, interval or text makes this easier than the full benchmark, and the scores are not comparable to published MATH results.",
]
CUT_OFF = (
    "- **Cut-off outputs.** Harder problems need longer reasoning. For this run the output limit was "
    "raised to {limit} tokens per answer in the eval's own config copy (the app is unchanged). An "
    "answer whose output looks cut off by the limit is counted as wrong and shown in the "
    '"Cut off" column; the detection is a heuristic (a provider reply with finish_reason=length, '
    "or JSON that opens more braces than it closes)."
)
STRICT = (
    "- **Strict answer matching.** An answer counts only if it is a pure number equal to the gold "
    'by value (18, 18.0 and $18 match; "18 dollars" does not). There is no fuzzy matching. '
    'Every question was sent with the extra line "{suffix}" and a missing or invalid answer '
    "counts as wrong."
)


def limitations(dataset: str, suffix: str, profile: dict[str, Any] | None = None) -> str:
    """The limitations block for a run; fixed text apart from the dataset-specific bullets."""
    contamination = CONTAMINATION.get(
        dataset, "The dataset is public and may be in the training data of these models."
    )
    out = [f"- **Training-data contamination.** {contamination}", SMALL_SAMPLE]
    if dataset == "math45":
        out += MATH_EXTRA
    out += [FREE_TIER, FALLBACKS, STRICT.format(suffix=suffix or "(none recorded)")]
    if profile and profile.get("max_tokens"):
        out.append(CUT_OFF.format(limit=profile["max_tokens"]))
    out += [JUDGE, EARLY_STOP, ONE_SAMPLE, COSTS]
    return "\n".join(out) + "\n"


# --- helpers ---


def dataset_label(name: str) -> str:
    cls = DATASETS.get(name)
    return (cls().label if cls else "") or name


def profile_text(profile: dict[str, Any] | None) -> str:
    """Eval-only settings that differ from the app's (output limit, request pacing)."""
    if not profile:
        return ""
    parts = []
    if profile.get("max_tokens"):
        parts.append(f"output limit {profile['max_tokens']} tokens per answer")
    for provider, value in sorted((profile.get("rpm") or {}).items()):
        parts.append(f"{provider} paced at {value:g} request(s)/min")
    return "Eval-only settings: " + ", ".join(parts) + ". " if parts else ""


def pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def interval(k: int, n: int) -> str:
    lo, hi = wilson(k, n)
    return f"{pct(k / n)} [{pct(lo)}, {pct(hi)}]" if n else "n/a"


def cell(text: Any, width: int = 36) -> str:
    """A table-safe, shortened code span for an answer."""
    if text is None:
        return "(none)"
    s = str(text).replace("\r", " ").replace("\n", " ").replace("|", "/").replace("`", "'")
    return f"`{s[: width - 1]}~`" if len(s) > width else f"`{s}`"


def table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(lines)


def cond(rec: dict[str, Any], name: str) -> dict[str, Any]:
    return rec["conditions"][name]


def correct_vector(records: list[dict[str, Any]], name: str) -> list[bool]:
    return [bool(cond(r, name)["correct"]) for r in records]


def model_names(records: list[dict[str, Any]]) -> dict[str, str]:
    """Most common model that answered each debater's turns without a fallback."""
    seen: dict[str, Counter[str]] = {}
    for r in records:
        for t in r.get("turns", []):
            if not t.get("fallback_used"):
                seen.setdefault(t["label"], Counter())[f"{t['provider']}/{t['model']}"] += 1
    return {label: c.most_common(1)[0][0] for label, c in seen.items()}


# --- sections ---


def accuracy_section(records: list[dict[str, Any]]) -> str:
    models = model_names(records)
    rows = []
    for name in ALL_ROWS:
        vals = [cond(r, name) for r in records]
        k = sum(v["correct"] for v in vals)
        prim = [v for v in vals if not v["fallback"]]
        pk = sum(v["correct"] for v in prim)
        n_fb = len(vals) - len(prim)
        label = ROW_LABELS[name]
        if name.startswith("A") and f"Debater {name[1]}" in models:
            label += f", {models[f'Debater {name[1]}']}"
        rows.append(
            [
                label,
                f"{k}/{len(vals)}",
                interval(k, len(vals)),
                f"{pk}/{len(prim)}",
                interval(pk, len(prim)),
                f"{n_fb} ({pct(n_fb / len(vals))})",
            ]
        )
    accs = [sum(cond(r, f"A{i}")["correct"] for r in records) / len(records) for i in (1, 2, 3)]
    rows.insert(3, ["A mean of the three single models", "-", pct(sum(accs) / 3), "-", "-", "-"])
    return table(
        [
            "Condition",
            "Correct",
            "Accuracy, all answers (95% Wilson)",
            "Primary-only correct",
            "Primary-only accuracy (95% Wilson)",
            "Answers via fallback",
        ],
        rows,
    )


def quality_cost_section(records: list[dict[str, Any]]) -> str:
    n = len(records)
    rows = []
    for name in ALL_ROWS:
        vals = [cond(r, name) for r in records]

        def mean(key: str, vals: list[dict[str, Any]] = vals) -> float:
            return sum(v["cost"][key] for v in vals) / n

        rows.append(
            [
                ROW_LABELS[name].split(" ")[0] if name != "D_vote" else "D-vote",
                str(sum(v["status"] == "non_numeric" for v in vals)),
                str(sum(v["status"] == "missing" for v in vals)),
                str(sum(bool(v.get("truncated")) for v in vals)),
                f"{mean('api_calls'):.1f}",
                f"{mean('tokens'):.0f}",
                f"{mean('latency_ms') / 1000:.1f}",
            ]
        )
    return table(
        [
            "Condition",
            "Non-numeric answers",
            "No valid answer",
            "Cut off",
            "Mean HTTP calls",
            "Mean tokens",
            "Mean latency (s)",
        ],
        rows,
    )


def comparisons(records: list[dict[str, Any]], seed: int) -> list[tuple[str, str, Comparison]]:
    pairs = [("D", "B"), ("C", "B"), ("D", "C"), ("D", "D_vote")]
    pairs += [("B", f"A{i}") for i in (1, 2, 3)]
    return [
        (x, y, compare(correct_vector(records, x), correct_vector(records, y), seed))
        for x, y in pairs
    ]


def comparison_section(records: list[dict[str, Any]], seed: int) -> str:
    out = []
    for i, (x, y, c) in enumerate(comparisons(records, seed)):
        xn, yn = SHORT[x], SHORT[y]
        out.append(
            [
                ("**" if i == 0 else "") + f"{xn} vs {yn}" + (" (primary)**" if i == 0 else ""),
                str(c.x_only),
                str(c.y_only),
                f"{100 * c.diff:+.1f} pp",
                f"[{100 * c.ci[0]:+.1f}, {100 * c.ci[1]:+.1f}] pp",
                f"{c.p:.3f}",
                reading(c, xn, yn),
            ]
        )
    return table(
        [
            "Comparison (X vs Y)",
            "X right, Y wrong",
            "Y right, X wrong",
            "Accuracy difference",
            "95% paired bootstrap",
            "McNemar p (exact)",
            "Reading",
        ],
        out,
    )


def fixed_broke_section(records: list[dict[str, Any]]) -> str:
    fixed = [r for r in records if not cond(r, "B")["correct"] and cond(r, "D")["correct"]]
    broke = [r for r in records if cond(r, "B")["correct"] and not cond(r, "D")["correct"]]

    def block(title: str, rows: list[dict[str, Any]]) -> str:
        if not rows:
            return f"**{title}: none.**"
        body = [
            [
                f"`{r['qid']}`",
                cell(r["gold"]),
                *(cell(cond(r, k)["answer"]) for k in ("A1", "A2", "A3", "B", "C", "D")),
            ]
            for r in sorted(rows, key=lambda r: r["qid"])
        ]
        head = ["Question", "Gold", "A1", "A2", "A3", "B", "C", "D"]
        return f"**{title} ({len(rows)}):**\n\n" + table(head, body)

    return (
        block("Debate fixed: majority vote (B) wrong, debate (D) right", fixed)
        + "\n\n"
        + block("Debate broke: majority vote (B) right, debate (D) wrong", broke)
    )


def debate_behaviour_section(records: list[dict[str, Any]], skipped: dict[str, str]) -> str:
    n = len(records)
    facts = [r["facts"] for r in records]
    early = sum(f["early_stopped"] for f in facts)
    c_eq = sum(f["c_equals_d"] for f in facts)
    bad_prefix = sum(not f["prefix_consistent"] for f in facts)
    ties = sum(cond(r, "B").get("note") == "tie" for r in records)
    judge_failed = sum(cond(r, "D").get("note") == "judge_failed" for r in records)
    replays = sum(f.get("cache_hits_d", 0) > 0 for f in facts)
    cut_off = sum(f.get("truncated_turns", 0) for f in facts)
    turns = [t for r in records for t in r.get("turns", [])]
    fb_turns = sum(bool(t.get("fallback_used")) for t in turns)
    fb_questions = sum(any(cond(r, k)["fallback"] for k in ALL_ROWS) for r in records)
    lines = [
        f"- Mean debate rounds run in D: {sum(f['rounds_run'] for f in facts) / n:.2f} "
        f"(max 3); stopped early on consensus: {early}/{n}; C identical to D: {c_eq}/{n}.",
        f"- B decided by a tie-break among tied answers: {ties}/{n}.",
        f"- Judge output unusable (majority fallback verdict used): {judge_failed}/{n}.",
        f"- Debater turns answered by a fallback model: {fb_turns}/{len(turns)}; "
        f"questions where any counted answer came via fallback: {fb_questions}/{n}.",
        f"- Outputs that looked cut off by the token limit (debater turns plus judge calls): "
        f"{cut_off} across {n} questions.",
        f"- Questions whose cost includes cached replays (re-run after an interruption): "
        f"{replays}/{n}.",
        f"- Questions where the C run did not reproduce D's rounds 0-1 answers: {bad_prefix}/{n}.",
    ]
    if skipped:
        lines.append(
            f"- Skipped after repeated provider errors (not in any number above): {len(skipped)}."
        )
    return "\n".join(lines)


def notes_section(records: list[dict[str, Any]], seed: int) -> list[str]:
    notes = []
    n = len(records)
    accs = {name: sum(correct_vector(records, name)) / n for name in ALL_ROWS}
    if n < SMALL_N:
        notes.append(
            f"**Very small sample (n = {n}).** Nothing here supports a conclusion about "
            "which condition is better; use these numbers to check that the pipeline works."
        )
    if all(a == 1.0 for a in accs.values()):
        notes.append(
            "**Every condition scored 100%.** With no wrong answers there are no discordant "
            "pairs, so no comparison is possible."
        )
    if all(a >= CEILING for a in accs.values()):
        notes.append(
            "**Ceiling effect.** Every condition is at or above 95%, so a difference between "
            "debate and the baselines cannot be detected on this dataset at this sample size. "
            "A harder question set would be needed."
        )
    primary = compare(correct_vector(records, "D"), correct_vector(records, "B"), seed)
    notes.append(
        f"**Primary comparison, D vs B:** {reading(primary, 'D', 'B')}."
        + ("" if primary.detectable else " Point estimates are not ranked.")
    )
    return notes


# --- assembly ---


def build_report(
    records: list[dict[str, Any]],
    manifest: dict[str, Any] | None = None,
    skipped: dict[str, str] | None = None,
) -> str:
    if not records:
        return "No finished questions yet, so there is nothing to report."
    manifest = manifest or {}
    config = manifest.get("config", {})
    seed = int(config.get("seed", 0))
    n = len(records)
    finished = sorted(r.get("finished_at", "") for r in records if r.get("finished_at"))
    span = f"{finished[0][:10]} to {finished[-1][:10]}" if finished else "unknown dates"
    suffix = config.get("prompt_suffix", "")
    head = (
        f"_Generated by `python -m eval.report` from {n} finished question(s) of "
        f"{dataset_label(config.get('dataset', 'gsm8k'))} (seed {seed}), run {span}. "
        f"Agent/prompt fingerprint `{config.get('agents_fingerprint', 'unknown')}`, "
        f"fallbacks {'allowed' if config.get('allow_fallback') else 'off'}, "
        f"early stop {'on' if config.get('early_stop', True) else 'off'}. "
        + (f'Each question was sent with the added line: "{suffix}". ' if suffix else "")
        + profile_text(config.get("profile"))
        + "Do not edit by hand._"
    )
    parts = [
        head,
        "\n\n".join(notes_section(records, seed)),
        "#### Accuracy\n\n" + accuracy_section(records),
        "#### Paired comparisons on the same questions\n\n"
        + comparison_section(records, seed)
        + "\n\nA difference is only reported when the exact McNemar test gives p < 0.05 and the "
        "paired bootstrap interval excludes 0. The first row is the pre-declared primary "
        "comparison; the others are exploratory and not corrected for multiple comparisons.",
        "#### Quality and cost per question\n\n" + quality_cost_section(records),
        "#### Debate fixed / broke\n\n" + fixed_broke_section(records),
        "#### How the debate ran\n\n" + debate_behaviour_section(records, skipped or {}),
        "#### Limitations\n\n"
        + limitations(config.get("dataset", "gsm8k"), suffix, config.get("profile")).rstrip(),
    ]
    return "\n\n".join(parts) + "\n"


def splice_readme(readme: str, block: str) -> str:
    """Replace the text between the markers; everything else is left byte for byte."""
    start, end = readme.find(START_MARKER), readme.find(END_MARKER)
    if (
        start == -1
        or end == -1
        or end < start
        or readme.count(START_MARKER) != 1
        or readme.count(END_MARKER) != 1
    ):
        raise ValueError(f"README needs exactly one {START_MARKER} before one {END_MARKER}")
    newline = "\r\n" if "\r\n" in readme else "\n"
    body = block.strip("\n").replace("\n", newline)
    return readme[: start + len(START_MARKER)] + newline + body + newline + readme[end:]


def load_run(run_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any] | None, dict[str, str]]:
    store = ResultStore(run_dir)
    skipped: dict[str, str] = {}
    if store.skipped_path.exists():
        try:
            skipped = json.loads(store.skipped_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            skipped = {}
    return store.load_questions(), store.read_manifest(), skipped


def main(
    argv: list[str] | None = None,
    *,
    results_dir: Path = RESULTS_DIR,
    readme: Path = README_PATH,
    out: Any = None,
) -> int:
    ap = argparse.ArgumentParser(prog="python -m eval.report", description=__doc__)
    ap.add_argument("--dataset", default="gsm8k")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--run", help="results folder name (default: <dataset>-s<seed>)")
    ap.add_argument("--readme", type=Path, default=readme)
    ap.add_argument(
        "--write-readme",
        action="store_true",
        help=f"rewrite the README between {START_MARKER} and {END_MARKER}",
    )
    args = ap.parse_args(argv)
    emit = out or (lambda text: sys.stdout.buffer.write((text + "\n").encode("utf-8")))

    run = args.run or f"{args.dataset}-s{args.seed}"
    run_dir = results_dir / run
    if not run_dir.exists():
        emit(f"error: no results folder at {run_dir}")
        return 1
    records, manifest, skipped = load_run(run_dir)
    report = build_report(records, manifest, skipped)
    emit(report)
    if args.write_readme:
        if not records:
            emit("error: nothing to write: no finished questions")
            return 1
        try:
            # bytes, so the file's own line endings are kept
            text = args.readme.read_bytes().decode("utf-8")
            args.readme.write_bytes(splice_readme(text, report).encode("utf-8"))
        except (OSError, ValueError) as e:
            emit(f"error: {e}")
            return 1
        emit(f"README updated: {args.readme}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
