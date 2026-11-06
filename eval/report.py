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

from app.core.settings import load_agents
from eval import EVAL_DIR, RESULTS_DIR
from eval.datasets import DATASETS, Dataset
from eval.stats import Comparison, compare, reading, wilson
from eval.store import ResultStore

START_MARKER = "<!-- EVAL_START -->"
END_MARKER = "<!-- EVAL_END -->"
README_PATH = EVAL_DIR.parent / "README.md"

LETTERS = "ABCDEFGHIJ"
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
JUDGE_D_ONLY = "- **Judge asymmetry.** Condition D includes a judge model that A and B do not have, and this run has no judge-free debate row, so debate and judge are not separated."
EARLY_STOP_D_ONLY = """- **Early stopping.** D is "up to 3 rounds": it stops once all debaters agree after at least one critique round, so its cost is below a fixed 3 rounds."""
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
    "mmlupro": (
        "MMLU-Pro is public and may well be in the training data of these models, so absolute "
        "accuracy says little about unseen questions; only the paired difference between "
        "conditions on the same questions is of interest."
    ),
}
MMLU_EXTRA = [
    "- **Not compute-matched.** D uses about 7 to 13 requests per question (three debaters for 2 to 4 rounds plus one judge call) against 3 for B and 1 for each A. Any advantage of D includes the extra compute; this run does not test whether debate beats spending the same calls another way.",
    "- **Weaker free-tier panel only.** The panel is a small free-tier lineup (see the model names in the accuracy table). Nothing here says how debate behaves with stronger models.",
    "- **Judge from the same model as one debater.** The judge is the same model as Debater 2 (same family and provider quota), so D may favour that debater's answer; this run cannot separate that from a real debate effect.",
    "- **Fixed subset.** Five categories (chemistry, physics, engineering, law, economics), a screened-then-frozen holdout of 60 questions. The numbers describe that sample, not MMLU-Pro as a whole.",
    "- **One pre-declared test.** D vs B is the only test. A1 to A3 are descriptive and carry no p-values.",
]
MATH_EXTRA = [
    "- **Small subset.** Only level 4 and 5 problems with a plain-integer answer are used, and only a small seeded sample of those; the numbers describe that sample, not MATH as a whole.",
    "- **Integer-only filter.** Dropping every problem whose answer is a fraction, expression, interval or text makes this easier than the full benchmark, and the scores are not comparable to published MATH results.",
]
CUT_OFF = (
    "- **Cut-off outputs.** Harder problems need longer reasoning. For this run the output limit was "
    "raised to {limit} in the eval's own config copy (the app is unchanged). An "
    "answer whose output looks cut off by the limit is counted as wrong and shown in the "
    '"Cut off" column; the detection is a heuristic, not a measurement: any reply of the turn '
    "(the first or the repair) counts if the provider reported finish_reason=length, if its JSON "
    "opens more braces than it closes, or, when no stop reason was stored, if its output reached "
    "95% of the limit. It can miss a cut-off or flag a reply that ended near the limit by chance."
)
STRICT_LETTER = (
    "- **Strict answer matching.** An answer counts only if it reduces to one letter that is "
    "one of that question's own options (A to D for 4 options, A to J for 10; surrounding "
    "whitespace, one pair of parentheses, a trailing period and case are ignored, and a trailing "
    '"the answer is X" in the final_answer field is accepted). Anything else is invalid and '
    "counts as wrong; invalid answers do not vote in B. Every question was sent with the extra "
    'line "{suffix}", where the last letter is replaced by that question\'s own last option.'
)
STRICT = (
    "- **Strict answer matching.** An answer counts only if it is a pure number equal to the gold "
    'by value (18, 18.0 and $18 match; "18 dollars" does not). There is no fuzzy matching. '
    'Every question was sent with the extra line "{suffix}" and a missing or invalid answer '
    "counts as wrong."
)


def limitations(
    dataset: str,
    suffix: str,
    profile: dict[str, Any] | None = None,
    has_c: bool = True,
    limits: dict[str, int] | None = None,
) -> str:
    """The limitations block for a run; fixed text apart from the dataset-specific bullets."""
    key = "mmlupro" if dataset.startswith("mmlupro") else dataset
    contamination = CONTAMINATION.get(
        key, "The dataset is public and may be in the training data of these models."
    )
    out = [f"- **Training-data contamination.** {contamination}", SMALL_SAMPLE]
    if dataset == "math45":
        out += MATH_EXTRA
    if key == "mmlupro":
        out += MMLU_EXTRA
    strict = STRICT_LETTER if key == "mmlupro" else STRICT
    out += [FREE_TIER, FALLBACKS, strict.format(suffix=suffix or "(none recorded)")]
    if profile and profile.get("max_tokens"):
        out.append(CUT_OFF.format(limit=limit_text(profile["max_tokens"], limits)))
    out += [JUDGE if has_c else JUDGE_D_ONLY, EARLY_STOP if has_c else EARLY_STOP_D_ONLY]
    out += [ONE_SAMPLE, COSTS]
    return "\n".join(out) + "\n"


# --- helpers ---


def dataset_label(name: str) -> str:
    cls = DATASETS.get(name)
    return (cls().label if cls else "") or name


def agent_label(agent_id: str) -> str:
    return agent_id.replace("_", " ").capitalize()


def limit_text(floor: int, limits: dict[str, int] | None = None) -> str:
    """'2048 tokens per answer (4096 for Debater 3)': the effective per-agent output limits.

    `limits` maps agent id -> effective max_tokens (insertion order = config order). The most
    common value is the headline (the smaller on a tie); agents that differ are listed after it.
    Without `limits` only the profile's floor is known and is stated alone.
    """
    if not limits:
        return f"{floor} tokens per answer"
    counts = Counter(limits.values())
    base = min(counts, key=lambda v: (-counts[v], v))
    others = [f"{v} for {agent_label(a)}" for a, v in limits.items() if v != base]
    return f"{base} tokens per answer" + (f" ({', '.join(others)})" if others else "")


def effective_limits(
    config_path: Path | None, profile: dict[str, Any] | None
) -> dict[str, int] | None:
    """Per-agent output limits the run used: the agents config raised to the profile's floor.

    The same rule as the eval's dry-run text (a floor: an agent set higher keeps its own limit).
    None if the config cannot be read, so the report then states the floor alone.
    """
    floor = (profile or {}).get("max_tokens")
    if not floor or config_path is None:
        return None
    try:
        agents = load_agents(config_path)
    except (OSError, ValueError):
        return None
    return {a.id: max(a.max_tokens or 0, floor) for a in agents.all_agents()}


def default_config_path(dataset: str) -> Path:
    """The agents file the dataset's runs use: the MMLU-Pro eval copy, else the app's."""
    if dataset.startswith("mmlupro"):
        return EVAL_DIR / "config" / "mmlupro_agents.yaml"
    return EVAL_DIR.parent / "backend" / "config" / "agents.yaml"


def profile_text(profile: dict[str, Any] | None, limits: dict[str, int] | None = None) -> str:
    """Eval-only settings that differ from the app's (output limit, request pacing)."""
    if not profile:
        return ""
    parts = []
    if profile.get("max_tokens"):
        parts.append(f"output limit {limit_text(profile['max_tokens'], limits)}")
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


def present_rows(records: list[dict[str, Any]]) -> list[str]:
    """The condition rows this run has (a run without C has no C or D-vote)."""
    have = set().union(*(r["conditions"] for r in records)) if records else set()
    return [name for name in ALL_ROWS if name in have]


def dataset_of(name: str) -> Dataset | None:
    factory = DATASETS.get(name)
    return factory() if factory else None


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
    for name in present_rows(records):
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


def quality_cost_section(records: list[dict[str, Any]], invalid_label: str) -> str:
    n = len(records)
    rows = []
    for name in present_rows(records):
        vals = [cond(r, name) for r in records]

        def mean(key: str, vals: list[dict[str, Any]] = vals) -> float:
            return sum(v["cost"][key] for v in vals) / n

        rows.append(
            [
                ROW_LABELS[name].split(" ")[0] if name != "D_vote" else "D-vote",
                str(sum(v["status"] in ("non_numeric", "invalid") for v in vals)),
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
            invalid_label,
            "No valid answer",
            "Cut off",
            "Mean HTTP calls",
            "Mean tokens",
            "Mean latency (s)",
        ],
        rows,
    )


def comparisons(
    records: list[dict[str, Any]], seed: int, exploratory: bool = True
) -> list[tuple[str, str, Comparison]]:
    pairs = [("D", "B")]
    if exploratory:
        have = set(present_rows(records))
        pairs += [p for p in [("C", "B"), ("D", "C"), ("D", "D_vote")] if set(p) <= have]
        pairs += [("B", f"A{i}") for i in (1, 2, 3)]
    return [
        (x, y, compare(correct_vector(records, x), correct_vector(records, y), seed))
        for x, y in pairs
    ]


def comparison_section(records: list[dict[str, Any]], seed: int, exploratory: bool = True) -> str:
    out = []
    for i, (x, y, c) in enumerate(comparisons(records, seed, exploratory)):
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
    have = set(present_rows(records))
    cols = [k for k in ("A1", "A2", "A3", "B", "C", "D") if k in have]
    fixed = [r for r in records if not cond(r, "B")["correct"] and cond(r, "D")["correct"]]
    broke = [r for r in records if cond(r, "B")["correct"] and not cond(r, "D")["correct"]]

    def block(title: str, rows: list[dict[str, Any]]) -> str:
        if not rows:
            return f"**{title}: none.**"
        body = [
            [
                f"`{r['qid']}`",
                cell(r["gold"]),
                *(cell(cond(r, k)["answer"]) for k in cols),
            ]
            for r in sorted(rows, key=lambda r: r["qid"])
        ]
        head = ["Question", "Gold", *cols]
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
    has_c = "C" in present_rows(records)
    c_eq = sum(f["c_equals_d"] for f in facts)
    bad_prefix = sum(not f["prefix_consistent"] for f in facts)
    ties = sum(cond(r, "B").get("note") == "tie" for r in records)
    judge_failed = sum(cond(r, "D").get("note") == "judge_failed" for r in records)
    replays = sum(f.get("cache_hits_d", 0) > 0 for f in facts)
    cut_off = sum(f.get("truncated_turns", 0) for f in facts)
    turns = [t for r in records for t in r.get("turns", [])]
    fb_turns = sum(bool(t.get("fallback_used")) for t in turns)
    fb_questions = sum(any(cond(r, k)["fallback"] for k in present_rows(records)) for r in records)
    lines = [
        f"- Mean debate rounds run in D: {sum(f['rounds_run'] for f in facts) / n:.2f} "
        f"(max 3); stopped early on consensus: {early}/{n}"
        + (f"; C identical to D: {c_eq}/{n}." if has_c else "."),
        f"- B decided by a tie-break among tied answers (tie rate): {ties}/{n} ({pct(ties / n)}).",
        f"- Judge output unusable (majority fallback verdict used): {judge_failed}/{n}.",
        f"- Debater turns answered by a fallback model: {fb_turns}/{len(turns)}; "
        f"questions where any counted answer came via fallback: {fb_questions}/{n}.",
        f"- Outputs that looked cut off by the token limit (debater turns plus judge calls): "
        f"{cut_off} across {n} questions.",
        f"- Questions whose cost includes cached replays (re-run after an interruption): "
        f"{replays}/{n}.",
    ]
    if has_c:
        lines.append(
            f"- Questions where the C run did not reproduce D's rounds 0-1 answers: "
            f"{bad_prefix}/{n}."
        )
    if skipped:
        lines.append(
            f"- Skipped after repeated provider errors (not in any number above): {len(skipped)}."
        )
    return "\n".join(lines)


def notes_section(records: list[dict[str, Any]], seed: int) -> list[str]:
    notes = []
    n = len(records)
    accs = {name: sum(correct_vector(records, name)) / n for name in present_rows(records)}
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


def letter_distribution_section(records: list[dict[str, Any]]) -> str:
    """How often each model picked each letter (position bias), next to the gold letters."""
    models = model_names(records)
    n = len(records)

    def row(label: str, answers: list[str | None]) -> list[str]:
        counts = Counter(a for a in answers if a in tuple(LETTERS))
        other = sum(a not in tuple(LETTERS) for a in answers)
        return [label, *(str(counts[ch]) for ch in LETTERS), str(other)]

    rows = [row("Gold", [r["gold"] for r in records])]
    for i in (1, 2, 3):
        name = f"A{i}"
        label = f"{name} {models.get(f'Debater {i}', '')}".strip()
        rows.append(row(label, [cond(r, name)["answer"] for r in records]))
    rows.append(row("D (judge)", [cond(r, "D")["answer"] for r in records]))
    return (
        table(["Source", *LETTERS, "Other / none"], rows)
        + f"\n\nCounts over {n} questions. A model far from the gold row has a position bias."
    )


def category_section(records: list[dict[str, Any]]) -> str:
    cats = sorted({r.get("meta", {}).get("category", "?") for r in records})
    names = [k for k in ("A1", "A2", "A3", "B", "D") if k in present_rows(records)]
    rows = []
    for cat in cats:
        part = [r for r in records if r.get("meta", {}).get("category", "?") == cat]
        rows.append(
            [cat, str(len(part))]
            + [f"{sum(cond(r, k)['correct'] for r in part)}/{len(part)}" for k in names]
        )
    return table(["Category", "n", *names], rows)


# --- assembly ---


def exploratory_section(records: list[dict[str, Any]]) -> str:
    """B and D where the round-0 answers had no majority or the majority was wrong. Descriptive."""
    groups: dict[str, list[dict[str, Any]]] = {"no_majority": [], "majority_wrong": []}
    for r in records:
        votes = Counter(
            cond(r, k)["answer"]
            for k in ("A1", "A2", "A3")
            if cond(r, k)["status"] in ("correct", "wrong")
        )
        if not votes or max(votes.values()) < 2:
            groups["no_majority"].append(r)
        elif not cond(r, "B")["correct"]:
            groups["majority_wrong"].append(r)
    both = groups["no_majority"] + groups["majority_wrong"]
    rows = []
    for title, part in (
        ("No majority (fewer than 2 matching valid round-0 answers)", groups["no_majority"]),
        ("Majority wrong", groups["majority_wrong"]),
        ("Either of the above", both),
    ):
        rows.append(
            [title, str(len(part))]
            + [f"{sum(cond(r, k)['correct'] for r in part)}/{len(part)}" for k in ("B", "D")]
        )
    return (
        "**Exploratory, descriptive and post-hoc.** These subsets were defined after seeing the "
        "results. No test is run. D vs B on all questions stays the only pre-declared comparison.\n\n"
        + table(["Round-0 outcome", "n", "B correct", "D correct"], rows)
        + "\n\nThe subsets are chosen by how B did, so B is wrong on every question in the "
        "'majority wrong' row by construction, and on 'no majority' B is a tie-break pick. "
        "Read D against B here with that selection in mind; the counts are small and say "
        "nothing about whether debate helps."
    )


def _round_letters(rec: dict[str, Any]) -> dict[int, dict[str, str | None]]:
    """round -> {debater label -> valid option letter or None}, from the saved debater turns."""
    out: dict[int, dict[str, str | None]] = {}
    for t in rec.get("turns", []):
        if "round" not in t or "label" not in t:
            continue
        a = t.get("answer")
        out.setdefault(int(t["round"]), {})[t["label"]] = a if a in tuple(LETTERS) else None
    return out


def swap_or_oscillation(rec: dict[str, Any]) -> tuple[bool, bool]:
    """(swap, oscillation) for one question, from valid letters only.

    Swap: two debaters exchange two different answers between consecutive rounds.
    Oscillation: one debater changes answer in two consecutive round steps (r to r+1 to r+2).
    """
    by_round = _round_letters(rec)
    swap = osc = False
    for r in sorted(by_round):
        cur, nxt = by_round[r], by_round.get(r + 1)
        if nxt is None:
            continue
        labels = sorted(cur)
        for i, a in enumerate(labels):
            for b in labels[i + 1 :]:
                x, y = cur[a], cur[b]
                if x and y and x != y and nxt.get(a) == y and nxt.get(b) == x:
                    swap = True
        after = by_round.get(r + 2)
        if after is not None:
            for lab in cur:
                p, q, s = cur[lab], nxt.get(lab), after.get(lab)
                if p and q and s and p != q and q != s:
                    osc = True
    return swap, osc


def final_plurality(rec: dict[str, Any]) -> tuple[str | None, bool]:
    """(most common valid letter in the last debate round, tied). (None, False) if no valid letter."""
    by_round = _round_letters(rec)
    if not by_round:
        return None, False
    votes = Counter(a for a in by_round[max(by_round)].values() if a)
    if not votes:
        return None, False
    top = max(votes.values())
    leaders = sorted(k for k, v in votes.items() if v == top)
    return (leaders[0], len(leaders) > 1)


def exploratory_dynamics_section(records: list[dict[str, Any]]) -> str:
    """Post-hoc diagnostics from the saved turns: swaps, final-round plurality, judge vs plurality."""
    n = len(records)
    flags = [swap_or_oscillation(r) for r in records]
    n_swap = sum(s for s, _ in flags)
    n_osc = sum(o for _, o in flags)
    n_any = sum(s or o for s, o in flags)
    pl = [final_plurality(r) for r in records]

    def acc(vals: list[bool]) -> str:
        return f"{sum(vals)}/{len(vals)}"

    untied = [(r, p) for r, (p, tied) in zip(records, pl, strict=True) if p and not tied]
    tied = [r for r, (p, t) in zip(records, pl, strict=True) if p and t]
    none = [r for r, (p, _t) in zip(records, pl, strict=True) if p is None]
    rows = [
        [
            "All questions",
            str(n),
            "-",
            acc([bool(cond(r, "D")["correct"]) for r in records]),
            acc([bool(cond(r, "B")["correct"]) for r in records]),
        ],
        [
            "Plurality unique",
            str(len(untied)),
            acc([p == r["gold"] for r, p in untied]),
            acc([bool(cond(r, "D")["correct"]) for r, _ in untied]),
            acc([bool(cond(r, "B")["correct"]) for r, _ in untied]),
        ],
        [
            "Plurality tied (flagged, plurality not scored)",
            str(len(tied)),
            "-",
            acc([bool(cond(r, "D")["correct"]) for r in tied]),
            acc([bool(cond(r, "B")["correct"]) for r in tied]),
        ],
        [
            "No valid last-round letter",
            str(len(none)),
            "-",
            acc([bool(cond(r, "D")["correct"]) for r in none]),
            acc([bool(cond(r, "B")["correct"]) for r in none]),
        ],
    ]
    # Judge vs plurality, on questions with a unique plurality and a valid judge letter.
    paired = [(r, p) for r, p in untied if cond(r, "D")["answer"] in tuple(LETTERS)]
    differ = [(r, p) for r, p in paired if cond(r, "D")["answer"] != p]
    j_right = sum(cond(r, "D")["answer"] == r["gold"] for r, _ in differ)
    p_right = sum(p == r["gold"] for r, p in differ)
    neither = len(differ) - j_right - p_right
    return (
        "**Exploratory, post-hoc, not pre-declared.** Everything below was chosen after seeing the "
        "results, is computed only from the saved per-question records, and has no test. "
        "D vs B on all questions stays the only pre-declared comparison.\n\n"
        f"**1. Swap / oscillation.** Questions with a swap (two debaters exchange two different "
        f"valid answers between consecutive rounds): {n_swap}/{n}. Questions where a debater "
        f"changed answer in two consecutive round steps: {n_osc}/{n}. Either: {n_any}/{n}.\n\n"
        "**2. Final-round plurality** (most common valid letter among the debaters in the last "
        "round; ties are not scored), next to D and B on the same questions:\n\n"
        + table(["Questions", "n", "Plurality correct", "D correct", "B correct"], rows)
        + f"\n\n**3. Judge vs plurality** (questions with a unique plurality and a valid judge "
        f"letter: {len(paired)}). The judge's letter differed from the plurality on "
        f"{len(differ)}/{len(paired)}. On those {len(differ)}: judge right {j_right}, plurality "
        f"right {p_right}, neither {neither}."
    )


def build_report(
    records: list[dict[str, Any]],
    manifest: dict[str, Any] | None = None,
    skipped: dict[str, str] | None = None,
    agents_config: Path | None = None,
) -> str:
    """`agents_config` is the agents yaml the run used (default: by dataset, see above)."""
    if not records:
        return "No finished questions yet, so there is nothing to report."
    manifest = manifest or {}
    config = manifest.get("config", {})
    seed = int(config.get("seed", 0))
    n = len(records)
    finished = sorted(r.get("finished_at", "") for r in records if r.get("finished_at"))
    span = f"{finished[0][:10]} to {finished[-1][:10]}" if finished else "unknown dates"
    suffix = config.get("prompt_suffix", "")
    dataset = dataset_of(config.get("dataset", "gsm8k"))
    exploratory = dataset.exploratory_tests if dataset else True
    invalid_label = dataset.invalid_label if dataset else "Non-numeric answers"
    has_c = "C" in present_rows(records)
    profile = config.get("profile")
    limits = effective_limits(
        agents_config or default_config_path(config.get("dataset", "gsm8k")), profile
    )
    head = (
        f"_Generated by `python -m eval.report` from {n} finished question(s) of "
        f"{dataset_label(config.get('dataset', 'gsm8k'))} (seed {seed}), run {span}. "
        f"Agent/prompt fingerprint `{config.get('agents_fingerprint', 'unknown')}`, "
        f"fallbacks {'allowed' if config.get('allow_fallback') else 'off'}, "
        f"early stop {'on' if config.get('early_stop', True) else 'off'}. "
        + (f'Each question was sent with the added line: "{suffix}". ' if suffix else "")
        + profile_text(profile, limits)
        + "Do not edit by hand._"
    )
    parts = [
        head,
        "\n\n".join(notes_section(records, seed)),
        "#### Accuracy\n\n" + accuracy_section(records),
        "#### Paired comparisons on the same questions\n\n"
        + comparison_section(records, seed, exploratory)
        + "\n\nA difference is only reported when the exact McNemar test gives p < 0.05 and the "
        "paired bootstrap interval excludes 0. The first row is the pre-declared primary "
        + (
            "comparison; the others are exploratory and not corrected for multiple comparisons."
            if exploratory
            else "comparison and the only test; the single-model rows are descriptive."
        ),
        "#### Quality and cost per question\n\n" + quality_cost_section(records, invalid_label),
        *(
            [
                "#### Answer letters\n\n" + letter_distribution_section(records),
                "#### Accuracy by category\n\n" + category_section(records),
            ]
            if dataset and dataset.answer_letters
            else []
        ),
        "#### Debate fixed / broke\n\n" + fixed_broke_section(records),
        *(
            [
                "#### Exploratory: disagreement by round-0 outcome\n\n"
                + exploratory_section(records),
                "#### Exploratory: debate dynamics (post-hoc)\n\n"
                + exploratory_dynamics_section(records),
            ]
            if dataset and dataset.answer_letters
            else []
        ),
        "#### How the debate ran\n\n" + debate_behaviour_section(records, skipped or {}),
        "#### Limitations\n\n"
        + limitations(config.get("dataset", "gsm8k"), suffix, profile, has_c, limits).rstrip(),
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
        "--config", type=Path, help="agents yaml the run used (default: by dataset, as in the run)"
    )
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
    report = build_report(records, manifest, skipped, args.config)
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
