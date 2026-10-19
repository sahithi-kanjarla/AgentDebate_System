"""Evaluation harness: does multi-agent debate beat cheaper baselines on the same free models?

Lives outside the app. It drives the orchestrator directly (no HTTP, so no rate limiter) and
reuses the app's response cache, providers and exact-answer comparison.
"""

from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
DATA_DIR = EVAL_DIR / "data"
CACHE_DIR = EVAL_DIR / "cache"
RESULTS_DIR = EVAL_DIR / "results"
