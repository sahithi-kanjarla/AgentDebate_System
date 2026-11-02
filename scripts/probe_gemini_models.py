"""Manual probe: which Gemini model ids answer on the OpenAI-compatible endpoint. YOU run this.

    cd backend
    uv run python ../scripts/probe_gemini_models.py gemini-3.1-flash-lite gemini-flash-lite-latest

Sends ONE tiny request per model id given (system + user, no JSON mode, max_tokens 64, no retries),
one at a time. Prints only the model id, the HTTP status and, for a non-200, the first 200
characters of the error body (key-scrubbed). Never prints keys, headers or replies. The key comes
from the same Settings code as the app (GEMINI_API_KEY).
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import httpx  # noqa: E402

from app.core.logging import scrub_text  # noqa: E402
from app.core.settings import Settings  # noqa: E402

URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
BODY_LIMIT = 200
MESSAGES = [
    {"role": "system", "content": "You are a terse assistant."},
    {"role": "user", "content": "Reply with the single word: ok"},
]


def report(model: str, status: str, detail: str = "") -> None:
    print(f"{model:<36} {status} {detail!r}".rstrip().replace(" ''", ""), flush=True)


async def probe(client: httpx.AsyncClient, key: str, secrets: list[str], model: str) -> None:
    body = {"model": model, "messages": MESSAGES, "max_tokens": 64}
    try:
        resp = await client.post(URL, json=body, headers={"Authorization": f"Bearer {key}"})
    except httpx.TimeoutException:
        return report(model, "timeout")
    except httpx.HTTPError as e:
        return report(model, type(e).__name__)
    detail = "" if resp.status_code == 200 else scrub_text(resp.text, secrets)[:BODY_LIMIT]
    report(model, f"HTTP {resp.status_code}", detail)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("models", nargs="+", help="model ids to try")
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()

    settings = Settings()
    key = settings.api_key("gemini_api_key")
    if not key:
        print("SKIP no key (GEMINI_API_KEY is empty)")
        return 0
    secrets = settings.secret_values()
    async with httpx.AsyncClient(timeout=args.timeout) as client:
        for model in args.models:
            await probe(client, key, secrets, model)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
