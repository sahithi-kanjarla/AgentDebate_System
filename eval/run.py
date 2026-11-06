"""Command line: python -m eval.run --dataset gsm8k --n 100 --seed 42

Resumable: finished questions are skipped, so the same command can be repeated over several days
as free-tier quotas reset. Stops cleanly (exit 0) when a provider is rate-limited or a budget cap
is reached. Never needs HTTP: the orchestrator is driven directly.
"""

import argparse
import asyncio
import math
import sys
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.logging import configure_logging
from app.core.settings import AgentsFile, Settings, get_settings, load_agents
from app.db.session import init_db, make_engine
from app.providers.base import LLMProvider
from app.providers.registry import ProviderRegistry
from eval import CACHE_DIR, DATA_DIR, RESULTS_DIR
from eval.budget import (
    DEFAULT_PROVIDER_CAPS,
    Budget,
    Ledger,
    estimate_per_question,
    parse_caps,
    utc_today,
)
from eval.datasets import Dataset, DatasetError, RunProfile, get_dataset, load_order
from eval.holdout import HOLDOUT_NAME, HoldoutRefused, check_holdout_ready, render_pin
from eval.runner import EvalSettings, Runner, agents_fingerprint, run_session, wrap_providers
from eval.store import ManifestMismatch, ResultStore

ProviderFactory = Callable[[AgentsFile], dict[str, LLMProvider]]


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m eval.run", description=__doc__)
    ap.add_argument("--dataset", default="gsm8k")
    ap.add_argument("--n", type=int, required=True, help="first n questions of the seeded order")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--run", help="results folder name (default: <dataset>-s<seed>)")
    ap.add_argument("--config", type=Path, help="agents yaml (default: the app's AGENTS_CONFIG)")
    ap.add_argument("--max-calls-per-day", type=int, help="global cap on HTTP requests per UTC day")
    ap.add_argument(
        "--max-calls-per-provider",
        default="",
        help=f"e.g. openrouter=40,groq=500 (0 = no cap). Defaults: {DEFAULT_PROVIDER_CAPS}",
    )
    ap.add_argument(
        "--sleep-between-s",
        type=float,
        help="pause after a question that sent requests (Groq ~8K tokens/min); default by "
        "dataset: 60 for gsm8k, 120 for math45",
    )
    ap.add_argument(
        "--max-tokens",
        type=int,
        help="raise every agent's output limit to at least this, in the eval's own config copy "
        "only (default by dataset: none for gsm8k, 4096 for math45; 0 = keep the app's values)",
    )
    ap.add_argument(
        "--rpm",
        default="",
        help="requests per minute per provider in the eval's config copy, e.g. groq=2 "
        "(default by dataset: none for gsm8k, groq=2 for math45; groq=0 removes it)",
    )
    ap.add_argument("--allow-fallback", action="store_true", help="let fallback models answer")
    ap.add_argument(
        "--no-early-stop", action="store_true", help="always run all 3 critique rounds in D"
    )
    ap.add_argument("--dry-run", action="store_true", help="print the call estimate and exit")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    ap.add_argument("--force", action="store_true", help="resume although settings changed")
    ap.add_argument(
        "--screen-run",
        help="mmlupro-holdout only: the finished screen's results folder (default: "
        "mmlupro-screen-s<screen seed>)",
    )
    ap.add_argument("--screen-seed", type=int, default=42, help="mmlupro-holdout only")
    ap.add_argument(
        "--accept-missed-screen",
        action="store_true",
        help="mmlupro-holdout only: start although the screen missed its target (recorded)",
    )
    return ap


def strip_fallbacks(agents: AgentsFile) -> AgentsFile:
    stripped = agents.model_copy(deep=True)
    for cfg in stripped.all_agents():
        cfg.fallbacks = []
    return stripped


def apply_profile(
    agents: AgentsFile, profile: RunProfile, max_tokens: int | None, rpm: dict[str, float]
) -> tuple[AgentsFile, dict[str, Any]]:
    """The eval's own copy of the agent config with a bigger output limit and request pacing.

    The app's agents.yaml and its loaded config are never modified. Returns the copy and what was
    applied (empty when nothing changed), which goes into the run manifest.
    """
    limit = profile.max_tokens if max_tokens is None else (max_tokens or None)
    pacing = {**profile.rpm, **rpm}
    out = agents.model_copy(deep=True)
    applied: dict[str, Any] = {}
    if limit:
        for cfg in out.all_agents():
            cfg.max_tokens = max(cfg.max_tokens or 0, limit)
        applied["max_tokens"] = limit
    used = {}
    for provider, value in pacing.items():
        if provider in out.providers:
            out.providers[provider].rpm = value or None
            used[provider] = value
    if used:
        applied["rpm"] = used
    return out, applied


def parse_rpm(text: str) -> dict[str, float]:
    rpm: dict[str, float] = {}
    for part in filter(None, (p.strip() for p in text.split(","))):
        name, sep, value = part.partition("=")
        try:
            number = float(value)
        except ValueError:
            number = -1
        if not sep or not name.strip() or number < 0:
            raise ValueError(f"bad --rpm entry {part!r}; expected provider=number")
        rpm[name.strip()] = number
    return rpm


def format_estimate(
    agents: AgentsFile,
    es: EvalSettings,
    todo: int,
    done: int,
    target: int,
    budget: Budget,
    sleep_s: float,
    run: str,
    profile: RunProfile | None = None,
    applied: dict[str, Any] | None = None,
) -> str:
    profile = profile or RunProfile()
    est = estimate_per_question(agents, es.rounds, es.d_min_critique, es.include_c)
    lines = [
        f"Run '{run}': {todo} question(s) to do, {done} already done (target n={target}).",
        "Estimated HTTP requests for those questions (cache hits are free; fallbacks not "
        "included; the upper bound allows "
        + (
            f"{profile.repair_factor:.1f}x for repair calls after cut-off output)"
            if profile.repair_factor > 1
            else "no repair calls)"
        )
        + ":",
        f"  {'provider':<12}{'per question':>14}{'total':>14}{'cap/day':>10}{'used today':>12}"
        f"{'days at cap':>13}",
    ]
    for provider, (lo, hi) in sorted(est.items()):
        hi = math.ceil(hi * profile.repair_factor)
        cap = budget.caps.get(provider)
        days = f"{math.ceil(hi * todo / cap)}" if cap and todo else "-"
        lines.append(
            f"  {provider:<12}{f'{lo}-{hi}':>14}{f'{lo * todo}-{hi * todo}':>14}"
            f"{cap if cap else 'none':>10}{budget.used(provider):>12}{days:>13}"
        )
    if budget.daily_cap:
        lines.append(f"  global cap {budget.daily_cap}/day, {budget.used()} used today")
    lines.append(
        f"Pauses between questions: {sleep_s:.0f}s each, about {sleep_s * todo / 60:.0f} min total."
    )
    applied = applied or {}
    if applied.get("max_tokens"):
        per_agent = ", ".join(f"{a.id} {a.max_tokens}" for a in agents.all_agents())
        lines.append(
            f"Eval-only output limit: {applied['max_tokens']} tokens per answer, as a floor: an "
            "agent configured higher keeps its own limit (the app's agents.yaml is unchanged). "
            f"Effective max_tokens: {per_agent}. "
            "It does not change how many requests are sent."
        )
    for provider, value in sorted(applied.get("rpm", {}).items()):
        if value:
            lo, hi = est.get(provider, (0, 0))
            hi = math.ceil(hi * profile.repair_factor)
            minutes = (lo / value, hi / value)  # calls / (calls per minute)
            lines.append(
                f"{provider} paced at {value:g} request(s)/min: at least {60 / value:.0f}s between "
                f"calls, so {lo}-{hi} calls take {minutes[0]:.1f}-{minutes[1]:.1f} min of pacing "
                "per question, on top of the pause."
            )
    return "\n".join(lines)


def tally(store: ResultStore) -> str:
    records = store.load_questions()
    if not records:
        return "No finished questions yet."
    counts: dict[str, list[int]] = {}
    for r in records:
        for name, c in r["conditions"].items():
            tot = counts.setdefault(name, [0, 0])
            tot[0] += int(c["correct"])
            tot[1] += 1
    cells = "  ".join(f"{k}={v[0]}/{v[1]}" for k, v in counts.items())
    return f"Correct so far over {len(records)} question(s): {cells}"


def main(
    argv: list[str] | None = None,
    *,
    provider_factory: ProviderFactory | None = None,
    dataset: Dataset | None = None,
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
    dataset: Dataset | None,
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

    try:
        dataset = dataset or get_dataset(args.dataset)
        agents, applied = apply_profile(
            agents, dataset.profile, args.max_tokens, parse_rpm(args.rpm)
        )
        order = load_order(dataset, args.seed, data_dir)
        questions = {q.qid: q for q in dataset.load()}
        sha = dataset.source_sha256()
    except (DatasetError, ValueError) as e:
        out(f"error: {e}")
        return 1
    screen_pin: dict[str, Any] | None = None
    if dataset.name == HOLDOUT_NAME:
        try:
            screen_pin = check_holdout_ready(
                dataset,
                agents,
                applied,
                results_dir=results_dir,
                data_dir=data_dir,
                screen_run=args.screen_run,
                screen_seed=args.screen_seed,
                allow_fallback=args.allow_fallback,
                accept_missed=args.accept_missed_screen,
            )
        except HoldoutRefused as e:
            if not args.dry_run:
                out(e.render())
                return 1
            out("Dry run, so only noting it: a real run would be refused.\n" + e.render())
        else:
            out(render_pin(screen_pin))
    sleep_s = dataset.profile.sleep_s if args.sleep_between_s is None else args.sleep_between_s
    n = min(args.n, len(order))
    run = args.run or f"{dataset.name}-s{args.seed}"
    es = EvalSettings(
        seed=args.seed,
        rounds=settings.default_rounds,
        min_critique_rounds=settings.min_critique_rounds,
        early_stop=not args.no_early_stop,
        include_c=dataset.runs_c,
    )
    config: dict[str, Any] = {
        "dataset": dataset.name,
        "seed": args.seed,
        "source_sha256": sha,
        "prompt_suffix": dataset.prompt_suffix,
        "rounds": es.rounds,
        "min_critique_rounds": es.min_critique_rounds,
        "early_stop": es.early_stop,
        "allow_fallback": args.allow_fallback,
        "agents_fingerprint": agents_fingerprint(agents),
        **({"profile": applied} if applied else {}),
        **({} if es.include_c else {"include_c": False}),
    }

    store = ResultStore(results_dir / run)
    try:
        manifest = store.check_config(config, force=args.force)
    except ManifestMismatch as e:
        out(f"error: {e}")
        return 1

    caps = {**DEFAULT_PROVIDER_CAPS, **parse_caps(args.max_calls_per_provider)}
    budget = Budget(
        Ledger(store.ledger_path),
        provider_caps=caps,
        daily_cap=args.max_calls_per_day,
        today=today,
    )

    done = store.done_ids()
    target = order[:n]
    todo = [questions[qid] for qid in target if qid not in done]
    out(
        format_estimate(
            agents, es, len(todo), n - len(todo), n, budget, sleep_s, run, dataset.profile, applied
        )
    )
    if args.dry_run:
        out("Dry run: nothing was sent.")
        return 0
    if not todo:
        out("Nothing to do.\n" + tally(store))
        return 0

    missing = _missing_keys(agents, settings) if provider_factory is None else []
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
    store.write_manifest(
        {
            "run": run,
            "created": manifest["created"] if manifest else now,
            "config": config,
            "order": order,
            **({"screen_pin": screen_pin} if screen_pin else {}),
            "sessions": [*(manifest or {}).get("sessions", []), {"started": now, "n": n}],
        }
    )

    summary = asyncio.run(
        _run(
            agents, settings, provider_factory, dataset, es, todo, store, budget,
            sleep_s, sleep, out, n, n - len(todo), cache_dir,
        )
    )  # fmt: skip
    out(
        f"Stopped: {summary.stop_reason}"
        + (f" - {summary.message}" if summary.message else "")
        + f". {summary.done_this_session} finished this session, {len(summary.skipped)} skipped."
    )
    out(tally(store))
    return 0


async def _run(
    agents: AgentsFile,
    settings: Settings,
    provider_factory: ProviderFactory | None,
    dataset: Dataset,
    es: EvalSettings,
    todo: list,
    store: ResultStore,
    budget: Budget,
    sleep_s: float,
    sleep: Callable[[float], Awaitable[None]],
    out: Callable[[str], None],
    total: int,
    already_done: int,
    cache_dir: Path,
):
    registry: ProviderRegistry | None = None
    if provider_factory is None:
        registry = _open_registry(agents, settings, cache_dir)
        providers = registry.providers()
    else:
        providers = provider_factory(agents)
    try:
        runner = Runner(agents, wrap_providers(providers, agents, budget), dataset, es)
        return await run_session(
            runner=runner,
            todo=todo,
            store=store,
            budget=budget,
            sleep_s=sleep_s,
            sleep=sleep,
            progress=out,
            total_questions=total,
            already_done=already_done,
        )
    finally:
        if registry is not None:
            await registry.aclose()


def _open_registry(agents: AgentsFile, settings: Settings, cache_dir: Path) -> ProviderRegistry:
    """Real providers on top of the eval's own response cache (never the app's database)."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    engine = make_engine(f"sqlite:///{(cache_dir / 'eval.db').as_posix()}")
    init_db(engine)
    return ProviderRegistry(agents, settings, engine)


def _missing_keys(agents: AgentsFile, settings: Settings) -> list[str]:
    """Names (never values) of key settings that are unset for the primary providers."""
    missing: set[str] = set()
    for cfg in agents.all_agents():
        if cfg.provider == "mock":
            continue
        setting = agents.providers[cfg.provider].api_key_setting
        if setting and not settings.api_key(setting):
            missing.add(setting.upper())
    return sorted(missing)


if __name__ == "__main__":
    sys.exit(main())
