"""Manual probe: which Mistral model ids answer, and their rate-limit headers. YOU run this.

    cd backend
    uv run python ../scripts/probe_mistral.py mistral-small-2603 mistral-small-latest

Sends ONE tiny request per model id given (system + user, no JSON mode, max_tokens 64, no retries),
5 seconds apart. Prints only the model id, the HTTP status, the first 200 characters of any error
body (key-scrubbed) and any response headers whose name contains "ratelimit" or "retry-after"
(names and values). Never prints keys or replies. The key comes from the same Settings code as
the app (MISTRAL_API_KEY).
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import httpx  # noqa: E402

from app.core.logging import scrub_text  # noqa: E402
from app.core.settings import Settings  # noqa: E402

URL = "https://api.mistral.ai/v1/chat/completions"
BODY_LIMIT = 200
GAP_SECONDS = 5.0
MESSAGES = [
    {"role": "system", "content": "You are a terse assistant."},
    {"role": "user", "content": "Reply with the single word: ok"},
]


def report(model: str, status: str, detail: str = "", headers: list[str] | None = None) -> None:
    print(f"{model:<28} {status} {detail!r}".rstrip().replace(" ''", ""), flush=True)
    for line in headers or []:
        print(f"    {line}", flush=True)


def limit_headers(resp: httpx.Response, secrets: list[str]) -> list[str]:
    out = []
    for name, value in resp.headers.items():
        low = name.lower()
        if "ratelimit" in low or "retry-after" in low:
            out.append(f"{name}: {scrub_text(value, secrets)}")
    return out


async def probe(client: httpx.AsyncClient, key: str, secrets: list[str], model: str) -> None:
    body = {"model": model, "messages": MESSAGES, "max_tokens": 64}
    try:
        resp = await client.post(URL, json=body, headers={"Authorization": f"Bearer {key}"})
    except httpx.TimeoutException:
        return report(model, "timeout")
    except httpx.HTTPError as e:
        return report(model, type(e).__name__)
    detail = "" if resp.status_code == 200 else scrub_text(resp.text, secrets)[:BODY_LIMIT]
    report(model, f"HTTP {resp.status_code}", detail, limit_headers(resp, secrets))


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("models", nargs="+", help="model ids to try")
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()

    settings = Settings()
    key = settings.api_key("mistral_api_key")
    if not key:
        print("SKIP no key (MISTRAL_API_KEY is empty)")
        return 0
    secrets = settings.secret_values()
    async with httpx.AsyncClient(timeout=args.timeout) as client:
        for i, model in enumerate(args.models):
            if i:
                await asyncio.sleep(GAP_SECONDS)
            await probe(client, key, secrets, model)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
