"""Manual smoke test for the real LLM providers. YOU run this, with your own keys.

    cd backend
    uv run python ../scripts/smoke_providers.py                       # every provider/model
    uv run python ../scripts/smoke_providers.py --only groq           # one provider (repeatable)
    uv run python ../scripts/smoke_providers.py --only groq --verbose-errors
    uv run python ../scripts/smoke_providers.py --list-models groq    # model IDs only
    uv run python ../scripts/smoke_providers.py --list-free           # OpenRouter free models

For each (provider, model) pair in config/agents.yaml (primary and fallback) it:
  1. lists the provider's models and checks the configured model ID is there, then
  2. sends ONE tiny completion built exactly like a real debate call (the registry's leg: same
     temperature, token limit, reasoning options, JSON-mode handling) and parses the reply with
     the same parser, including its repair step. No retries and no cache, to spare free quotas.

Output is PASS / FAIL / SKIP, latency, and a safe error category such as "rate_limited (HTTP 429)".
It never prints keys, prompts, replies, headers, or full response bodies. With --verbose-errors a
FAIL also shows the provider's error "message" and "type" (200 characters max, key-scrubbed).
Exit code is 1 if anything FAILed. Keys are read from .env by the app's settings code.
"""

import argparse
import asyncio
import contextlib
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import httpx  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from app.core.logging import scrub_text  # noqa: E402
from app.core.settings import AgentConfig, AgentsFile, Settings, load_agents  # noqa: E402
from app.debate.parsing import parse_with_repair  # noqa: E402
from app.providers.base import Message, ProviderError  # noqa: E402
from app.providers.registry import ProviderRegistry, _model_ids  # noqa: E402
from app.providers.resilience import RetryPolicy  # noqa: E402

PROMPT = [
    Message(role="system", content="You reply with a single JSON object and nothing else."),
    Message(role="user", content='Return exactly this JSON object: {"ok": true}'),
]
OPENROUTER_MODELS = "https://openrouter.ai/api/v1/models"
VERBOSE_LIMIT = 200


class SmokeReply(BaseModel):
    ok: bool


def line(status: str, provider: str, model: str, detail: str = "") -> None:
    print(f"{status:<5} {provider:<11} {model:<46} {detail}".rstrip(), flush=True)


def describe_error(error: ProviderError, secrets: list[str]) -> str:
    """The provider's error message and type, truncated and scrubbed. Nothing else."""
    message = scrub_text(error.detail or "(no message)", secrets)[:VERBOSE_LIMIT]
    error_type = scrub_text(error.error_type or "-", secrets)[:VERBOSE_LIMIT]
    return f"message={message!r} type={error_type}"


async def list_models(client: httpx.AsyncClient, base_url: str, key: str | None):
    """Returns (list of model ids | None, failure category | None). Never raises."""
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        resp = await client.get(base_url.rstrip("/") + "/models", headers=headers)
    except httpx.TimeoutException:
        return None, "timeout"
    except httpx.HTTPError:
        return None, "unreachable"
    if resp.status_code in (401, 403):
        return None, f"unauthorized (HTTP {resp.status_code})"
    if resp.status_code != 200:
        return None, f"listing_unavailable (HTTP {resp.status_code})"
    try:
        return [str(m["id"]) for m in resp.json()["data"]], None
    except (ValueError, KeyError, TypeError):
        return None, "listing_unreadable"


def _client(http: httpx.AsyncClient | None, timeout: float):
    return contextlib.nullcontext(http) if http else httpx.AsyncClient(timeout=timeout)


async def list_models_command(
    settings: Settings, agents: AgentsFile, provider: str, http: httpx.AsyncClient | None = None
) -> int:
    """Print only the model IDs the provider's /models endpoint returns."""
    pcfg = agents.providers.get(provider)
    if pcfg is None:
        print(f"unknown provider {provider!r}; configured: {', '.join(agents.providers)}")
        return 2
    key = settings.api_key(pcfg.api_key_setting)
    if pcfg.api_key_setting and not key:
        print(f"SKIP no key ({pcfg.api_key_setting.upper()} is empty)")
        return 0
    async with _client(http, 30) as client:
        ids, problem = await list_models(client, pcfg.base_url, key)
    if ids is None:
        print(f"FAIL {problem}")
        return 1
    for model_id in sorted(ids):
        print(model_id)
    return 0


async def check(
    settings: Settings,
    agents: AgentsFile,
    registry: ProviderRegistry,
    provider: str,
    model: str,
    agent: AgentConfig,
    *,
    verbose: bool = False,
    timeout: float = 60.0,
    http: httpx.AsyncClient | None = None,
) -> bool:
    """Run both checks for one pair. Returns True on PASS (or SKIP)."""
    pcfg = agents.providers[provider]
    key = settings.api_key(pcfg.api_key_setting)
    if pcfg.api_key_setting and not key:
        line("SKIP", provider, model, f"no key ({pcfg.api_key_setting.upper()} is empty)")
        return True

    async with _client(http, timeout) as client:
        ids, problem = await list_models(client, pcfg.base_url, key)
    if problem and problem.startswith(("unauthorized", "unreachable", "timeout")):
        line("FAIL", provider, model, problem)
        return False
    if ids is not None and not (_model_ids(model) & {i for x in ids for i in _model_ids(x)}):
        line("FAIL", provider, model, "model_not_found (not in provider's model list)")
        return False

    leg = registry.build_leg(provider, model, agent)
    assert leg is not None  # the key check above guarantees the leg is configured
    started = time.monotonic()
    try:
        outcome = await parse_with_repair(leg, PROMPT, SmokeReply)
    except ProviderError as e:
        line("FAIL", provider, model, str(e))  # str() is a safe category, never provider text
        if verbose:
            print("      " + describe_error(e, settings.secret_values()), flush=True)
        return False
    except Exception as e:  # noqa: BLE001 - print the type only, never the message
        line("FAIL", provider, model, f"unexpected {type(e).__name__}")
        return False
    if not outcome.valid:
        line("FAIL", provider, model, "reply_was_not_valid_json_after_repair")
        return False
    notes = []
    if outcome.api_calls > 1:
        notes.append(f"{outcome.api_calls} requests")
    if outcome.calls > 1:
        notes.append("needed JSON repair")
    if problem:
        notes.append(f"model list: {problem}")
    suffix = f"({', '.join(notes)})" if notes else ""
    line("PASS", provider, model, f"{int((time.monotonic() - started) * 1000)} ms {suffix}".strip())
    return True


async def list_free() -> int:
    """Print OpenRouter's current free models. Public endpoint, no key needed."""
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(OPENROUTER_MODELS)
        models = resp.json()["data"]
    except (httpx.HTTPError, ValueError, KeyError):
        print("could not fetch OpenRouter's model list")
        return 1
    free = [m for m in models if str(m["id"]).endswith(":free") or m["id"] == "openrouter/free"]
    free.sort(key=lambda m: -(m.get("context_length") or 0))
    print(f"{len(free)} free models on OpenRouter (json = advertises response_format):")
    for m in free:
        json_ok = "response_format" in (m.get("supported_parameters") or [])
        print(f"  {m['id']:<60} ctx={m.get('context_length')} json={json_ok}")
    return 0


def pairs_to_check(agents: AgentsFile, only: list[str]) -> list[tuple[str, str, AgentConfig]]:
    """Distinct (provider, model) pairs with the first agent that uses each, in config order."""
    pairs: list[tuple[str, str, AgentConfig]] = []
    seen: set[tuple[str, str]] = set()
    for agent in agents.all_agents():
        for provider, model in [
            (agent.provider, agent.model),
            *((f.provider, f.model) for f in agent.fallbacks),
        ]:
            if provider == "mock" or (provider, model) in seen:
                continue
            if only and provider not in only:
                continue
            seen.add((provider, model))
            pairs.append((provider, model, agent))
    return pairs


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--only", action="append", default=[], help="limit to a provider name")
    parser.add_argument("--verbose-errors", action="store_true", help="show provider error text")
    parser.add_argument("--list-models", metavar="PROVIDER", help="print model IDs and exit")
    parser.add_argument("--list-free", action="store_true", help="list OpenRouter free models")
    parser.add_argument("--timeout", type=float, default=None, help="override seconds per request")
    parser.add_argument(
        "--no-dotenv", action="store_true", help="ignore .env files (use only the environment)"
    )
    args = parser.parse_args()

    if args.list_free:
        return await list_free()

    settings = Settings(_env_file=None) if args.no_dotenv else Settings()
    agents = load_agents(settings.agents_config)
    if args.timeout:
        for pcfg in agents.providers.values():
            pcfg.timeout_s = args.timeout
    if args.list_models:
        return await list_models_command(settings, agents, args.list_models)

    pairs = pairs_to_check(agents, args.only)
    if not pairs:
        print("nothing to check (no matching providers in the agents config)")
        return 1
    # No engine => no cache; one attempt per call => no quota burned on retries.
    registry = ProviderRegistry(agents, settings, None, policy=RetryPolicy(max_attempts=1))
    try:
        outcomes = []
        for provider, model, agent in pairs:  # sequential on purpose: gentle on free tiers
            outcomes.append(
                await check(
                    settings,
                    agents,
                    registry,
                    provider,
                    model,
                    agent,
                    verbose=args.verbose_errors,
                    timeout=args.timeout or agents.providers[provider].timeout_s,
                )
            )
    finally:
        await registry.aclose()
    failed = outcomes.count(False)
    print(f"\n{len(outcomes) - failed} ok/skipped, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
