"""Manual probe for OpenRouter free models. YOU run this, with your own key.

    cd backend
    uv run python ../scripts/probe_openrouter.py MODEL_ID [MODEL_ID ...]

For each model it sends ONE tiny request (system + user, no JSON mode, no retries), one model at a
time, and prints the HTTP status, the first 200 characters of any error body (key-scrubbed), and
the rate-limit headers it can see (any header with "ratelimit" or "retry-after" in its name). It
never prints keys, other headers, prompts, or successful replies. The key is read by the app's
Settings code. Model IDs come from the command line only.
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import httpx  # noqa: E402

from app.core.logging import scrub_text  # noqa: E402
from app.core.settings import Settings  # noqa: E402

URL = "https://openrouter.ai/api/v1/chat/completions"
BODY_LIMIT = 200
MESSAGES = [
    {"role": "system", "content": "You are a terse assistant."},
    {"role": "user", "content": "Reply with the single word: ok"},
]


def rate_headers(resp: httpx.Response) -> str:
    found = {
        k.lower(): v
        for k, v in resp.headers.items()
        if "ratelimit" in k.lower() or "retry-after" in k.lower()
    }
    return " ".join(f"{k}={v}" for k, v in sorted(found.items())) or "(no rate-limit headers)"


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("models", nargs="+", help="OpenRouter model IDs")
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--max-tokens", type=int, default=64)
    parser.add_argument("--pause", type=float, default=4.0, help="seconds between requests")
    args = parser.parse_args()

    settings = Settings()
    key = settings.api_key("openrouter_api_key")
    if not key:
        print("SKIP no key (OPENROUTER_API_KEY is empty)")
        return 0
    secrets = settings.secret_values()
    async with httpx.AsyncClient(timeout=args.timeout) as client:
        for i, model in enumerate(args.models):
            if i:
                await asyncio.sleep(args.pause)  # free models: about 20 requests/minute
            body = {"model": model, "messages": MESSAGES, "max_tokens": args.max_tokens}
            try:
                resp = await client.post(URL, json=body, headers={"Authorization": f"Bearer {key}"})
            except httpx.TimeoutException:
                print(f"{model}\n  timeout", flush=True)
                continue
            except httpx.HTTPError as e:
                print(f"{model}\n  {type(e).__name__}", flush=True)
                continue
            print(f"{model}\n  HTTP {resp.status_code}  {rate_headers(resp)}")
            if resp.status_code != 200:
                print(f"  error: {scrub_text(resp.text, secrets)[:BODY_LIMIT]!r}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
