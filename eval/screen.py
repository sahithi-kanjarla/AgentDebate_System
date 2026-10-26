"""Difficulty screen for the MMLU-Pro experiment: every screen question, one call, one model at a
time, for BOTH the weakest panel model (checks the floor) and the strongest (checks the ceiling).

    python -m eval.screen --config eval/config/mmlupro_agents.yaml
    python -m eval.screen --config eval/config/mmlupro_agents.yaml --report     # no calls

Each call is that model's own round-0 debater call (its persona, the same prompt, parser, token
limit and answer normaliser as in the debate), so the screen accuracy is what A1 / A2 will be.
Resumable and budgeted like eval.run: finished questions are skipped, requests are counted in the
run's ledger against the same daily caps, and it stops cleanly at a cap or a rate limit.

Target (each model): 40-70% overall and no category below 25%. This tool only reports against it.
"""

import argparse
import asyncio
import hashlib
import sys
from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.logging import configure_logging
from app.core.settings import AgentConfig, AgentsFile, Settings, get_settings, load_agents
from app.debate.orchestrator import TurnRecord
from app.debate.parsing import ParseOutcome, parse_with_repair
from app.debate.prompts import mode_task, render_messages
from app.providers.base import LLMProvider, ProviderError
from app.schemas import DebaterOutput
from eval import CACHE_DIR, DATA_DIR, RESULTS_DIR
from eval.budget import DEFAULT_PROVIDER_CAPS, Budget, Ledger, parse_caps, utc_today
from eval.datasets import DatasetError, Question
from eval.mmlupro import (
    CATEGORIES,
    LETTERS,
    SCREEN_SEED,
    MMLUPro,
    MMLUProScreen,
    extractor_fingerprint,
    selection_path,
)
from eval.run import (
    ProviderFactory,
    _open_registry,
    apply_profile,
    parse_rpm,
    strip_fallbacks,
)
from eval.runner import MAX_ATTEMPTS, agents_fingerprint, classify_error, looks_truncated
from eval.stats import wilson
from eval.store import ManifestMismatch, ResultStore

TARGET_LOW, TARGET_HIGH = 0.40, 0.70
CATEGORY_FLOOR = 0.25
DEFAULT_AGENTS = ("debater_1", "debater_2")  # Gemma (floor) and gpt-oss-20b (ceiling)
DEFAULT_SLEEP_S = 5.0  # one call per question; Groq is paced by the config's rpm


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m eval.screen", description=__doc__)
    ap.add_argument("--config", type=Path, help="agents yaml (default: the app's AGENTS_CONFIG)")
    ap.add_argument("--seed", type=int, default=SCREEN_SEED, help="screen selection seed")
    ap.add_argument("--agents", default=",".join(DEFAULT_AGENTS), help="agent ids to screen")
    ap.add_argument("--run", help="results folder name (default: mmlupro-screen-s<seed>)")
    ap.add_argument("--max-calls-per-day", type=int, help="global cap on HTTP requests per UTC day")
    ap.add_argument("--max-calls-per-provider", default="", help="e.g. groq=500 (0 = no cap)")
    ap.add_argument("--sleep-between-s", type=float, default=DEFAULT_SLEEP_S)
    ap.add_argument("--max-tokens", type=int, help="eval-only output limit (0 = keep the config)")
    ap.add_argument("--rpm", default="", help="requests per minute per provider, e.g. groq=4")
    ap.add_argument("--allow-fallback", action="store_true")
    ap.add_argument("--report", action="store_true", help="print the saved results, send nothing")
    ap.add_argument("--dry-run", action="store_true", help="print the call estimate and exit")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    ap.add_argument("--force", action="store_true", help="resume although settings changed")
    return ap


def slug(model: str) -> str:
    return "".join(c if c.isalnum() or c in "-._" else "_" for c in model)


def interleaved(questions: list[Question]) -> list[Question]:
    """Round-robin over categories, so a run cut short by a cap is still balanced."""
    by_cat: dict[str, list[Question]] = {}
    for q in questions:
        by_cat.setdefault(q.meta["category"], []).append(q)
    out: list[Question] = []
    for i in range(max((len(v) for v in by_cat.values()), default=0)):
        out += [v[i] for v in by_cat.values() if i < len(v)]
    return out


# --- one question ---


def _turn_record(cfg: AgentConfig, o: ParseOutcome[DebaterOutput]) -> TurnRecord:
    """Just enough of a TurnRecord for the shared cut-off heuristic."""
    return TurnRecord(
        round=0, agent_id=cfg.id, label=cfg.id, persona=cfg.persona, provider=o.provider,
        model=o.model, prompt_hash="", raw_text=o.raw_text, parsed_json=None, valid=o.valid,
        tokens_in=o.tokens_in, tokens_out=o.tokens_out, latency_ms=o.latency_ms,
        error=o.error, attempts=list(o.attempts),
    )  # fmt: skip


async def ask(
    cfg: AgentConfig, provider: LLMProvider, dataset: MMLUPro, q: Question
) -> dict[str, Any]:
    """The model's round-0 call for one question, as a stored record. Raises ProviderError."""
    messages = render_messages(
        "debater",
        persona=cfg.persona,
        persona_prompt=cfg.persona_prompt,
        mode="answer",
        task=mode_task("answer"),
        question=dataset.prompt(q),
    )
    try:
        outcome = await parse_with_repair(provider, messages, DebaterOutput)
    except ProviderError as e:
        if classify_error(str(e)) != "model":
            raise
        # An empty reply that hit the output limit is the model's own failure: a real, wrong result.
        outcome = ParseOutcome[DebaterOutput](value=None, raw_text="", error=str(e))
        outcome.attempts = []
    raw = outcome.value.final_answer if outcome.value else None
    answer = dataset.normalize_answer(raw, q) if raw is not None else None
    score = dataset.score(q, answer)
    turn = _turn_record(cfg, outcome)
    return {
        "qid": q.qid,
        "category": q.meta["category"],
        "gold": q.gold,
        "n_options": q.meta["n_options"],
        "agent": cfg.id,
        "model": f"{outcome.provider or cfg.provider}/{outcome.model or cfg.model}",
        "answer_raw": raw,
        "answer": answer,
        "status": score.status,
        "correct": score.correct,
        "truncated": looks_truncated(turn, cfg.max_tokens),
        "finish_reason": outcome.finish_reason,
        "repair_used": outcome.repair_used,
        "fallback_used": outcome.fallback_used,
        "tokens_in": outcome.tokens_in,
        "tokens_out": outcome.tokens_out,
        "api_calls": outcome.api_calls,
        "error": outcome.error[:300] if outcome.error else None,
        "raw_tail": outcome.raw_text[-300:],
        "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


# --- a session ---


class Stop(Exception):
    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind, self.message = kind, message


async def screen_agent(
    cfg: AgentConfig,
    provider: LLMProvider,
    dataset: MMLUPro,
    todo: list[Question],
    store: ResultStore,
    budget: Budget,
    sleep_s: float,
    sleep: Callable[[float], Awaitable[None]],
    out: Callable[[str], None],
    already_done: int,
    total: int,
) -> int:
    """Screen `todo` with one agent. Returns how many finished; raises Stop at a cap or limit."""
    done = 0
    skipped: dict[str, str] = {}
    for i, q in enumerate(todo):
        blocked = budget.can_start({cfg.provider: 1})
        if blocked:
            raise Stop("budget", f"daily budget reached ({blocked})")
        before = budget.used(cfg.provider)
        record: dict[str, Any] | None = None
        last_error = ""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                record = await ask(cfg, provider, dataset, q)
                break
            except ProviderError as e:
                kind = classify_error(str(e))
                if kind in ("budget", "quota", "config"):
                    raise Stop(kind, f"{cfg.provider}: {e}") from e
                last_error = str(e)
                out(f"  {q.qid}: attempt {attempt}/{MAX_ATTEMPTS} failed: {last_error}")
        if record is None:
            skipped[q.qid] = last_error
            store.write_skipped(skipped)
            continue
        store.save_question(record)
        done += 1
        out(
            f"[{cfg.id} {already_done + done}/{total}] {q.qid} {record['category']} "
            f"gold={record['gold']} answer={record['answer']!s} {record['status']}"
        )
        if budget.used(cfg.provider) > before and sleep_s > 0 and i < len(todo) - 1:
            await sleep(sleep_s)
    return done


# --- report ---


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(records)
    k = sum(r["correct"] for r in records)
    cats = {}
    for cat in CATEGORIES:
        part = [r for r in records if r["category"] == cat]
        cats[cat] = {"n": len(part), "correct": sum(r["correct"] for r in part)}
    letters = Counter(r["answer"] for r in records if r["answer"] in tuple(LETTERS))
    low = [c for c, v in cats.items() if v["n"] and v["correct"] / v["n"] < CATEGORY_FLOOR]
    return {
        "n": n,
        "correct": k,
        "accuracy": k / n if n else 0.0,
        "wilson": wilson(k, n),
        "invalid": sum(r["status"] == "invalid" for r in records),
        "missing": sum(r["status"] == "missing" for r in records),
        "truncated": sum(bool(r["truncated"]) for r in records),
        "repairs": sum(bool(r["repair_used"]) for r in records),
        "fallback": sum(bool(r["fallback_used"]) for r in records),
        "tokens_out": sum(r["tokens_out"] for r in records),
        "categories": cats,
        "letters": {ch: letters[ch] for ch in LETTERS},
        "below_floor": low,
    }


def verdict(s: dict[str, Any], expected: int) -> tuple[bool, list[str]]:
    """(met, reasons it was missed). A partial screen never counts as met."""
    why = []
    if s["n"] < expected:
        why.append(f"only {s['n']} of {expected} questions finished")
    if s["n"]:
        if s["accuracy"] < TARGET_LOW:
            why.append(f"overall {100 * s['accuracy']:.0f}% is below {100 * TARGET_LOW:.0f}%")
        if s["accuracy"] > TARGET_HIGH:
            why.append(f"overall {100 * s['accuracy']:.0f}% is above {100 * TARGET_HIGH:.0f}%")
    why += [f"{c} is below {100 * CATEGORY_FLOOR:.0f}%" for c in s["below_floor"]]
    return not why, why


GUIDANCE = (
    "If the screen missed: too hard (overall below 40% or a category below 25%) -> replace that "
    "category with an easier one or use a stronger model for the weakest seat; too easy (above "
    "70%) -> replace the easiest category or use a weaker model. Any change needs a new, disjoint "
    "screen seed (python -m eval.mmlupro select --kind screen --seed N) and must be made before "
    "any holdout run. Categories are 12 questions each, so the check is coarse: 2 of 12 is below "
    "the floor, 3 of 12 is not."
)


def format_report(
    per_agent: dict[str, tuple[str, list[dict[str, Any]]]], expected: int, extra: str = ""
) -> str:
    lines = ["## MMLU-Pro screen", ""]
    for agent_id, (model, records) in per_agent.items():
        s = summarize(records)
        met, why = verdict(s, expected)
        lo, hi = s["wilson"]
        lines += [
            f"### {agent_id}: {model}",
            "",
            f"- Overall {s['correct']}/{s['n']} = {100 * s['accuracy']:.1f}% "
            f"(95% Wilson {100 * lo:.1f}-{100 * hi:.1f}%); target "
            f"{100 * TARGET_LOW:.0f}-{100 * TARGET_HIGH:.0f}%.",
            "- Per category: "
            + ", ".join(f"{c} {v['correct']}/{v['n']}" for c, v in s["categories"].items()),
            f"- Invalid answers: {s['invalid']}; no answer: {s['missing']}; cut off by the token "
            f"limit: {s['truncated']}; needed a repair call: {s['repairs']}; via fallback: "
            f"{s['fallback']}.",
            "- Letters chosen: " + " ".join(f"{ch}:{n}" for ch, n in s["letters"].items()),
            f"- **{'Within target.' if met else 'MISSED: ' + '; '.join(why) + '.'}**",
            "",
        ]
    if per_agent and not all(verdict(summarize(r), expected)[0] for _m, r in per_agent.values()):
        lines += [GUIDANCE, ""]
    return "\n".join(lines) + (extra and "\n" + extra)


# --- command line ---


def main(
    argv: list[str] | None = None,
    *,
    provider_factory: ProviderFactory | None = None,
    dataset: MMLUPro | None = None,
    settings: Settings | None = None,
    input_fn: Callable[[str], str] = input,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    today: Callable[[], str] = utc_today,
    results_dir: Path = RESULTS_DIR,
    cache_dir: Path = CACHE_DIR,
    data_dir: Path = DATA_DIR,
    out: Callable[[str], None] = print,
) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _main(
            args, provider_factory, dataset, settings, input_fn, sleep, today,
            results_dir, cache_dir, data_dir, out,
        )  # fmt: skip
    except KeyboardInterrupt:
        out("Interrupted. Finished questions are saved; re-run the same command to continue.")
        return 130


def _main(
    args: argparse.Namespace,
    provider_factory: ProviderFactory | None,
    dataset: MMLUPro | None,
    settings: Settings | None,
    input_fn: Callable[[str], str],
    sleep: Callable[[float], Awaitable[None]],
    today: Callable[[], str],
    results_dir: Path,
    cache_dir: Path,
    data_dir: Path,
    out: Callable[[str], None],
) -> int:
    settings = settings or get_settings()
    configure_logging("WARNING", settings.secret_values())
    agents = load_agents(args.config or settings.agents_config)
    if not args.allow_fallback:
        agents = strip_fallbacks(agents)
    wanted = [a.strip() for a in args.agents.split(",") if a.strip()]
    by_id = {a.id: a for a in agents.debaters}
    unknown = [a for a in wanted if a not in by_id]
    if unknown or not wanted:
        out(f"error: unknown agent id(s) {unknown or '(none given)'}; known: {sorted(by_id)}")
        return 1
    try:
        dataset = dataset or MMLUProScreen(data_dir, selection_path("screen", args.seed, data_dir))
        agents, applied = apply_profile(
            agents, dataset.profile, args.max_tokens, parse_rpm(args.rpm)
        )
        questions = interleaved(dataset.load())
        sha = dataset.source_sha256()
    except (DatasetError, ValueError, OSError) as e:
        out(f"error: {e}")
        return 1
    by_id = {a.id: a for a in agents.debaters}
    run = args.run or f"mmlupro-screen-s{args.seed}"
    root = results_dir / run

    stores: dict[str, ResultStore] = {}
    for agent_id in wanted:
        cfg = by_id[agent_id]
        stores[agent_id] = ResultStore(root / f"{agent_id}-{slug(cfg.model)}")

    def saved() -> dict[str, tuple[str, list[dict[str, Any]]]]:
        return {
            a: (f"{by_id[a].provider}/{by_id[a].model}", stores[a].load_questions()) for a in wanted
        }

    if args.report:
        out(format_report(saved(), len(questions)))
        return 0

    configs: dict[str, dict[str, Any]] = {}
    manifests: dict[str, dict[str, Any] | None] = {}
    try:
        for agent_id in wanted:
            cfg = by_id[agent_id]
            config = {
                "dataset": dataset.name,
                "seed": args.seed,
                "source_sha256": sha,
                "prompt_suffix": dataset.prompt_suffix,
                "prompt_suffix_sha256": hashlib.sha256(dataset.prompt_suffix.encode()).hexdigest(),
                "extractor": extractor_fingerprint(),
                "agent": agent_id,
                "provider": cfg.provider,
                "model": cfg.model,
                "max_tokens": cfg.max_tokens,
                "temperature": cfg.temperature,
                "allow_fallback": args.allow_fallback,
                "agents_fingerprint": agents_fingerprint(agents),
                **({"profile": applied} if applied else {}),
            }
            configs[agent_id] = config
            manifests[agent_id] = stores[agent_id].check_config(config, force=args.force)
    except ManifestMismatch as e:
        out(f"error: {e}")
        return 1

    caps = {**DEFAULT_PROVIDER_CAPS, **parse_caps(args.max_calls_per_provider)}
    budget = Budget(
        Ledger(root / "ledger.json"),
        provider_caps=caps,
        daily_cap=args.max_calls_per_day,
        today=today,
    )

    todo = {a: [q for q in questions if q.qid not in stores[a].done_ids()] for a in wanted}
    out(
        f"Screen '{run}': {len(questions)} questions per model, one call each "
        f"({dataset.describe(questions)})."
    )
    out(
        f"  {'agent':<11}{'provider/model':<42}{'to do':>6}{'calls':>7}{'cap/day':>9}"
        f"{'used today':>11}"
    )
    for a in wanted:
        cfg = by_id[a]
        cap = budget.caps.get(cfg.provider)
        calls = f"{len(todo[a])}-{len(todo[a]) * 2}"  # a repair call at most doubles it
        out(
            f"  {a:<11}{cfg.provider + '/' + cfg.model:<42}{len(todo[a]):>6}{calls:>7}"
            f"{cap if cap else 'none':>9}{budget.used(cfg.provider):>11}"
        )
    if args.dry_run:
        out("Dry run: nothing was sent.")
        return 0
    if not any(todo.values()):
        out("Nothing to do.\n" + format_report(saved(), len(questions)))
        return 0
    if provider_factory is None:
        settings_needed = {agents.providers[by_id[a].provider].api_key_setting for a in wanted}
        missing = sorted(s.upper() for s in settings_needed if s and not settings.api_key(s))
        if missing:
            out("error: no API key configured for: " + ", ".join(missing) + " (set them in .env)")
            return 1
    if not args.yes:
        try:
            answer = input_fn("Proceed? [y/N] ")
        except EOFError:
            answer = ""
        if answer.strip().lower() not in ("y", "yes"):
            out("Aborted.")
            return 0

    now = datetime.now(UTC).isoformat(timespec="seconds")
    for a in wanted:
        old = manifests[a]
        stores[a].write_manifest(
            {
                "run": run,
                "created": old["created"] if old else now,
                "config": configs[a],
                "sessions": [*(old or {}).get("sessions", []), {"started": now}],
            }
        )

    stop = asyncio.run(
        _run(
            agents, settings, provider_factory, dataset, wanted, by_id, todo, stores, budget,
            args.sleep_between_s, sleep, out, len(questions), cache_dir,
        )
    )  # fmt: skip
    if stop:
        out(f"Stopped: {stop.kind} - {stop.message}. Re-run the same command to continue.")
    out(format_report(saved(), len(questions)))
    return 0


async def _run(
    agents: AgentsFile,
    settings: Settings,
    provider_factory: ProviderFactory | None,
    dataset: MMLUPro,
    wanted: list[str],
    by_id: dict[str, AgentConfig],
    todo: dict[str, list[Question]],
    stores: dict[str, ResultStore],
    budget: Budget,
    sleep_s: float,
    sleep: Callable[[float], Awaitable[None]],
    out: Callable[[str], None],
    total: int,
    cache_dir: Path,
) -> Stop | None:
    from eval.budget import CountingProvider

    registry = None
    if provider_factory is None:
        registry = _open_registry(agents, settings, cache_dir)
        providers = registry.providers()
    else:
        providers = provider_factory(agents)
    try:
        for a in wanted:
            cfg = by_id[a]
            counted = CountingProvider(providers[a], budget, cfg.provider)
            try:
                await screen_agent(
                    cfg, counted, dataset, todo[a], stores[a], budget, sleep_s, sleep, out,
                    total - len(todo[a]), total,
                )  # fmt: skip
            except Stop as stop:
                return stop
        return None
    finally:
        if registry is not None:
            await registry.aclose()


if __name__ == "__main__":
    sys.exit(main())
