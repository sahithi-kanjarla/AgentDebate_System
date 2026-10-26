"""Manual probe for the Gemma HTTP 500 on Gemini's OpenAI-compatible endpoint. YOU run this.

Mode 1, four fixed shapes (needs a model id):
    cd backend
    uv run python ../scripts/probe_gemma.py gemma-4-26b-a4b-it [gemma-4-31b-it]
  (a) user only  (b) system+user  (c) user+JSON mode  (d) system+user+JSON mode

Mode 2, the REAL request a debate would send, built from an agents config, then variants:
    uv run python ../scripts/probe_gemma.py --real --config ../eval/config/mmlupro_agents.yaml
  Reports which config/provider json_mode applied and the exact body shape (no message text, no
  keys), then sends: the real body; the real body minus response_format, temperature, max_tokens
  and extra model_options, one at a time; a minimal body; a body with the system text folded into
  the user turn; the smoke-test prompt with the agent's settings; a JSON-repair shaped conversation
  (system, user, assistant, user); and the real body through the openai SDK (its headers).

One request per case, one at a time, no retries. Prints only the HTTP status and, for a non-200,
the first 200 characters of the error body (key-scrubbed). Never prints keys or headers. Keys come
from the same Settings code as the app.
"""

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import httpx  # noqa: E402
import openai  # noqa: E402

from app.core.logging import scrub_text  # noqa: E402
from app.core.settings import Settings, load_agents  # noqa: E402
from app.debate.prompts import mode_task, render_messages  # noqa: E402
from app.providers.base import Message  # noqa: E402
from app.providers.registry import ProviderRegistry  # noqa: E402
from app.providers.resilience import RetryPolicy  # noqa: E402

URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
BODY_LIMIT = 200
SYSTEM = {"role": "system", "content": "You reply with a single JSON object and nothing else."}
USER = {"role": "user", "content": 'Return exactly this JSON object: {"ok": true}'}
CASES = [
    ("a user only", [USER], False),
    ("b system+user", [SYSTEM, USER], False),
    ("c user+json", [USER], True),
    ("d system+user+json", [SYSTEM, USER], True),
]
QUESTION = "What is 17 * 24? Show your work."


def report(label: str, model: str, status: str, detail: str = "") -> None:
    print(f"{model:<22} {label:<26} {status} {detail!r}".rstrip().replace(" ''", ""), flush=True)


async def post(client, key, secrets, model, label, body) -> None:
    try:
        resp = await client.post(URL, json=body, headers={"Authorization": f"Bearer {key}"})
    except httpx.TimeoutException:
        return report(label, model, "timeout")
    except httpx.HTTPError as e:
        return report(label, model, type(e).__name__)
    detail = "" if resp.status_code == 200 else scrub_text(resp.text, secrets)[:BODY_LIMIT]
    report(label, model, f"HTTP {resp.status_code}", detail)


async def fixed_shapes(client, key, secrets, model: str) -> None:
    for label, messages, json_mode in CASES:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 64,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        await post(client, key, secrets, model, label, body)


def real_body(leg) -> dict[str, Any]:
    """The request body OpenAICompatibleProvider would build, minus the messages."""
    body: dict[str, Any] = {"model": leg.model, "temperature": leg.temperature}
    if leg.max_tokens:
        body[leg.token_param] = leg.max_tokens
    body.update(leg.extra_body)  # the SDK merges extra_body into the top level of the JSON
    if leg._json_mode_enabled:
        body["response_format"] = {"type": "json_object"}
    return body


def describe(config: Path, agent_id: str, pcfg, leg, body, messages) -> None:
    print(f"config            {config}")
    print(f"agent / provider  {agent_id} / {leg.name}  json_mode setting: {pcfg.json_mode!r}")
    print(f"json mode on      {leg._json_mode_enabled}  (sent: {'response_format' in body})")
    print(f"token param       {leg.token_param}")
    print(f"body fields       {sorted([*body, 'messages'])}")
    scalars = {k: v for k, v in body.items() if k != "model"}
    print(f"body values       model={body['model']} {scalars}")
    print(f"messages          {[(m.role, len(m.content)) for m in messages]} (role, chars)")
    print(f"extra_body keys   {sorted(leg.extra_body)}\n", flush=True)


async def real_mode(args, settings: Settings) -> int:
    agents = load_agents(args.config)
    agent = next((a for a in agents.all_agents() if a.id == args.agent), None)
    if agent is None:
        print(f"unknown agent {args.agent!r}; configured: {[a.id for a in agents.all_agents()]}")
        return 2
    pcfg = agents.providers[agent.provider]
    key = settings.api_key(pcfg.api_key_setting)
    if not key:
        print(f"SKIP no key ({(pcfg.api_key_setting or '').upper()} is empty)")
        return 0
    registry = ProviderRegistry(agents, settings, None, policy=RetryPolicy(max_attempts=1))
    leg = registry.build_leg(agent.provider, agent.model, agent)
    if leg.name != "gemini":
        print(f"agent {agent.id} is on {leg.name}, not gemini; this probe only targets Gemini")
        return 2
    messages = render_messages(
        "debater",
        persona=agent.persona,
        persona_prompt=agent.persona_prompt,
        mode="answer",
        task=mode_task("answer"),
        question=QUESTION,
    )
    body = real_body(leg)
    describe(args.config, agent.id, pcfg, leg, body, messages)
    dump = [m.model_dump() for m in messages]
    smoke = [
        Message(role="system", content=SYSTEM["content"]).model_dump(),
        Message(role="user", content=USER["content"]).model_dump(),
    ]
    folded = [{"role": "user", "content": f"{messages[0].content}\n\n{messages[1].content}"}]
    repair = [
        *dump,
        {"role": "assistant", "content": "Sorry, here is my answer."},
        {"role": "user", "content": "Your reply was not valid JSON. Reply with only the JSON."},
    ]
    model = leg.model

    def without(*fields: str) -> dict[str, Any]:
        return {k: v for k, v in body.items() if k not in fields}

    cases: list[tuple[str, dict[str, Any]]] = [
        ("real body", {**body, "messages": dump}),
        ("- response_format", {**without("response_format"), "messages": dump}),
        ("- temperature", {**without("temperature"), "messages": dump}),
        ("- max_tokens", {**without(leg.token_param), "messages": dump}),
        ("- extra model_options", {**without(*leg.extra_body), "messages": dump}),
        ("minimal (model+messages)", {"model": model, "messages": dump}),
        ("real, system folded in user", {**body, "messages": folded}),
        ("smoke prompt, real settings", {**body, "messages": smoke}),
        ("repair-shaped conversation", {**body, "messages": repair}),
    ]
    secrets = settings.secret_values()
    async with httpx.AsyncClient(timeout=args.timeout) as client:
        for label, case_body in cases:
            if label == "- extra model_options" and not leg.extra_body:
                report(label, model, "n/a (no model_options)")
                continue
            await post(client, key, secrets, model, label, case_body)
    # The same real body through the openai SDK, which adds its own headers.
    sdk_body = {k: v for k, v in body.items() if k not in ("model", *leg.extra_body)}
    try:
        await leg._client.chat.completions.create(
            model=model, messages=dump, extra_body=leg.extra_body or None, **sdk_body
        )
        report("real body via openai SDK", model, "HTTP 200")
    except openai.APIStatusError as e:
        report(
            "real body via openai SDK",
            model,
            f"HTTP {e.status_code}",
            scrub_text(str(e), secrets)[:BODY_LIMIT],
        )
    except openai.OpenAIError as e:
        report("real body via openai SDK", model, type(e).__name__)
    await registry.aclose()
    return 0


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("model", nargs="?", help="model ID (fixed-shape mode)")
    parser.add_argument("model2", nargs="?", help="optional second model ID (fixed-shape mode)")
    parser.add_argument("--real", action="store_true", help="probe the real debater_1 request")
    parser.add_argument("--config", type=Path, help="agents yaml for --real")
    parser.add_argument("--agent", default="debater_1", help="agent id for --real")
    parser.add_argument("--timeout", type=float, default=90.0)
    args = parser.parse_args()

    settings = Settings()
    if args.real:
        if not args.config:
            parser.error("--real needs --config")
        return await real_mode(args, settings)
    if not args.model:
        parser.error("give a model id, or use --real --config ...")
    key = settings.api_key("gemini_api_key")
    if not key:
        print("SKIP no key (GEMINI_API_KEY is empty)")
        return 0
    secrets = settings.secret_values()
    async with httpx.AsyncClient(timeout=args.timeout) as client:
        for model in [m for m in (args.model, args.model2) if m]:
            await fixed_shapes(client, key, secrets, model)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
