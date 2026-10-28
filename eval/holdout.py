"""The holdout guard: the MMLU-Pro holdout is spent only after a finished, matching screen.

    python -m eval.holdout check [--config eval/config/mmlupro_agents.yaml]

`eval.run --dataset mmlupro-holdout` calls check_holdout_ready() first and refuses to start when:
  - the screen run, or either screened agent's results, are missing;
  - any screen question is unfinished (the finished ids must equal the screen selection);
  - the screen was run with another prompt, extractor, dataset file, model or agent config
    (every hash and setting its manifest recorded is compared with what the holdout would use);
  - the screen missed its target (unless --accept-missed-screen).
Nothing here talks to a model provider or reads .env.
"""

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.settings import AgentsFile, load_agents
from eval import DATA_DIR, EVAL_DIR, RESULTS_DIR
from eval.datasets import Dataset, DatasetError
from eval.mmlupro import (
    SCREEN_SEED,
    MMLUProHoldout,
    MMLUProScreen,
    extractor_fingerprint,
    selection_path,
)
from eval.runner import agents_fingerprint
from eval.store import ResultStore

HOLDOUT_NAME = "mmlupro-holdout"
DEFAULT_CONFIG = EVAL_DIR / "config" / "mmlupro_agents.yaml"
# What a screen manifest records and the holdout must reproduce exactly.
PINNED = (
    "source_sha256",
    "prompt_suffix",
    "prompt_suffix_sha256",
    "extractor",
    "provider",
    "model",
    "max_tokens",
    "temperature",
    "allow_fallback",
    "agents_fingerprint",
    "profile",
)


class HoldoutRefused(Exception):
    def __init__(self, reasons: list[str]) -> None:
        self.reasons = reasons
        super().__init__("; ".join(reasons))

    def render(self) -> str:
        lines = ["error: the holdout will not start. The screen is not ready:"]
        lines += [f"  - {r}" for r in self.reasons]
        lines.append("See docs/MMLUPRO_RUN.md for what to do about each.")
        return "\n".join(lines)


def default_screen_run(seed: int = SCREEN_SEED) -> str:
    return f"mmlupro-screen-s{seed}"


def expected_config(
    dataset: Dataset,
    agents: AgentsFile,
    applied: dict[str, Any],
    agent_id: str,
    allow_fallback: bool,
) -> dict[str, Any]:
    """The pinned part of the config `eval.screen` writes for `agent_id`, as the holdout run
    (same agents file, same profile, same prompt, same extractor) would produce it."""
    cfg = next(a for a in agents.debaters if a.id == agent_id)
    return {
        "source_sha256": dataset.source_sha256(),
        "prompt_suffix": dataset.prompt_suffix,
        "prompt_suffix_sha256": hashlib.sha256(dataset.prompt_suffix.encode()).hexdigest(),
        "extractor": extractor_fingerprint(),
        "provider": cfg.provider,
        "model": cfg.model,
        "max_tokens": cfg.max_tokens,
        "temperature": cfg.temperature,
        "allow_fallback": allow_fallback,
        "agents_fingerprint": agents_fingerprint(agents),
        "profile": applied or None,
    }


def _short(value: Any) -> str:
    text = json.dumps(value, sort_keys=True) if not isinstance(value, str) else value
    return text if len(text) <= 24 else text[:21] + "..."


def check_holdout_ready(
    dataset: Dataset,
    agents: AgentsFile,
    applied: dict[str, Any],
    *,
    results_dir: Path = RESULTS_DIR,
    data_dir: Path = DATA_DIR,
    screen_run: str | None = None,
    screen_seed: int = SCREEN_SEED,
    allow_fallback: bool = False,
    accept_missed: bool = False,
) -> dict[str, Any]:
    """Raise HoldoutRefused (listing every problem) unless the screen is finished and matches.

    Returns the pin to store in the holdout manifest. `dataset` is the holdout dataset; `agents`
    and `applied` are the eval's own config copy and profile exactly as the holdout run uses them.
    """
    from eval import screen  # lazy: screen imports eval.run, which imports this module

    run = screen_run or default_screen_run(screen_seed)
    root = results_dir / run
    reasons: list[str] = []
    try:
        wanted = [
            q.qid
            for q in MMLUProScreen(data_dir, selection_path("screen", screen_seed, data_dir)).load()
        ]
        expected_sha = dataset.source_sha256()
    except (DatasetError, OSError, ValueError) as e:
        raise HoldoutRefused([f"cannot load the screen selection: {e}"]) from e
    if not root.is_dir():
        raise HoldoutRefused([f"no screen results at {root}; run python -m eval.screen first"])

    by_id = {a.id: a for a in agents.debaters}
    pin: dict[str, Any] = {
        "screen_run": run,
        "screen_seed": screen_seed,
        "checked": datetime.now(UTC).isoformat(timespec="seconds"),
        "accepted_missed": False,
        "agents": {},
    }
    for agent_id in screen.DEFAULT_AGENTS:
        if agent_id not in by_id:
            reasons.append(f"{agent_id}: not in the agents config")
            continue
        cfg = by_id[agent_id]
        store = ResultStore(root / f"{agent_id}-{screen.slug(cfg.model)}")
        manifest = store.read_manifest()
        if manifest is None:
            reasons.append(
                f"{agent_id}: no screen manifest at {store.root} (not screened with {cfg.model}?)"
            )
            continue
        recorded = manifest.get("config", {})
        want = expected_config(dataset, agents, applied, agent_id, allow_fallback)
        for key in PINNED:
            if recorded.get(key) != want[key]:
                reasons.append(
                    f"{agent_id}: screen {key} was {_short(recorded.get(key))}, the holdout "
                    f"would use {_short(want[key])}"
                )
        if recorded.get("source_sha256") != expected_sha:
            reasons.append(f"{agent_id}: the screen used a different MMLU-Pro download")
        records = store.load_questions()
        done = {r["qid"] for r in records}
        if done != set(wanted):
            missing = len(set(wanted) - done)
            extra = len(done - set(wanted))
            reasons.append(
                f"{agent_id}: {len(done & set(wanted))} of {len(wanted)} screen questions finished"
                + (f", {missing} missing" if missing else "")
                + (f", {extra} not in the selection" if extra else "")
            )
            continue
        summary = screen.summarize(records)
        met, why = screen.verdict(summary, len(wanted))
        pin["agents"][agent_id] = {
            "model": f"{cfg.provider}/{cfg.model}",
            "n": summary["n"],
            "accuracy": round(summary["accuracy"], 4),
            "target_met": met,
            "agents_fingerprint": recorded.get("agents_fingerprint"),
            "extractor": recorded.get("extractor"),
            "prompt_suffix_sha256": recorded.get("prompt_suffix_sha256"),
        }
        if not met:
            if accept_missed:
                pin["accepted_missed"] = True
            else:
                reasons.append(
                    f"{agent_id}: the screen missed its target ({'; '.join(why)}); fix the panel "
                    "and re-screen with a new seed, or pass --accept-missed-screen"
                )
    if reasons:
        raise HoldoutRefused(reasons)
    return pin


def render_pin(pin: dict[str, Any]) -> str:
    lines = [f"Holdout guard: screen '{pin['screen_run']}' is finished and matches."]
    for agent_id, a in pin["agents"].items():
        lines.append(
            f"  {agent_id} {a['model']}: {100 * a['accuracy']:.1f}% of {a['n']}, "
            f"target {'met' if a['target_met'] else 'MISSED (accepted)'}"
        )
    return "\n".join(lines)


def main(
    argv: list[str] | None = None,
    *,
    results_dir: Path = RESULTS_DIR,
    data_dir: Path = DATA_DIR,
    out: Any = print,
) -> int:
    from eval.run import apply_profile, strip_fallbacks  # lazy, see check_holdout_ready

    ap = argparse.ArgumentParser(prog="python -m eval.holdout", description=__doc__)
    ap.add_argument("command", choices=["check"])
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--screen-run")
    ap.add_argument("--screen-seed", type=int, default=SCREEN_SEED)
    ap.add_argument("--allow-fallback", action="store_true")
    ap.add_argument("--accept-missed-screen", action="store_true")
    args = ap.parse_args(argv)
    try:
        agents = load_agents(args.config)
        if not args.allow_fallback:
            agents = strip_fallbacks(agents)
        dataset = MMLUProHoldout(data_dir)
        agents, applied = apply_profile(agents, dataset.profile, None, {})
        pin = check_holdout_ready(
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
        out(e.render())
        return 1
    except (DatasetError, OSError, ValueError) as e:
        out(f"error: {e}")
        return 1
    out(render_pin(pin))
    return 0


if __name__ == "__main__":
    sys.exit(main())
