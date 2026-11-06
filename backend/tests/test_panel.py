"""The landing page panel.json must match the agents config and not leak the slot mapping."""

import json

from app.debate.panel import DEFAULT_CONFIG, DEFAULT_OUTPUT, build_panel, lab_for, render


def test_committed_panel_file_matches_the_config():
    committed = json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))
    assert committed == build_panel(DEFAULT_CONFIG), (
        "frontend/public/panel.json is stale: run `uv run python -m app.debate.panel`"
    )


def test_models_are_sorted_so_slot_order_is_not_revealed():
    panel = build_panel(DEFAULT_CONFIG)
    models = [d["model"] for d in panel["debaters"]]
    assert models == sorted(models)
    assert all("id" not in d and "persona" not in d for d in panel["debaters"])


def test_lab_comes_from_the_model_not_the_host():
    assert lab_for("openai/gpt-oss-20b") == "OpenAI"
    assert lab_for("gemini-3.1-flash-lite") == "Google"
    assert lab_for("ministral-14b-2512") == "Mistral AI"
    assert lab_for("something-new") == "Unknown"


def test_render_ends_with_newline():
    assert render(build_panel(DEFAULT_CONFIG)).endswith("}\n")
