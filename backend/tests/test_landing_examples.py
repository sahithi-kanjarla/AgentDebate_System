"""The landing page's examples.json must come from the stored holdout run and meet its own rule."""

import json

from eval import RESULTS_DIR
from eval.landing_examples import (
    OUTPUT,
    PICKS,
    RUN,
    build,
    qualifies,
    render,
    split_question,
)

FORBIDDEN = ("provider", "model", "gemini", "groq", "mistral", "openai")


def test_committed_file_matches_the_stored_results():
    committed = json.loads(OUTPUT.read_text(encoding="utf-8"))
    assert committed == build(), "stale: run `python -m eval.landing_examples` from the repo root"


def test_every_pick_meets_the_selection_rule():
    folder = RESULTS_DIR / RUN / "questions"
    for qid in PICKS:
        doc = json.loads((folder / f"{qid}.json").read_text(encoding="utf-8"))
        assert qualifies(doc), qid
        assert doc["conditions"]["D"]["correct"] is True


def test_no_model_or_provider_information_is_published():
    text = render(build()).lower()
    for word in FORBIDDEN:
        assert f'"{word}"' not in text, word
    assert "gemini-" not in text and "gpt-oss" not in text and "ministral" not in text


def test_split_question_separates_options():
    stem, options = split_question("What is 1+1?\n\nA. 1\nB. 2\nC. 3")
    assert stem == "What is 1+1?"
    assert options == [
        {"letter": "A", "text": "1"},
        {"letter": "B", "text": "2"},
        {"letter": "C", "text": "3"},
    ]


def test_each_example_has_options_and_rounds_for_every_debater():
    for ex in build()["examples"]:
        assert len(ex["options"]) >= 2
        assert ex["gold"] in {o["letter"] for o in ex["options"]}
        assert ex["rounds"][0]["round"] == 0
        assert all(len(r["answers"]) == 3 for r in ex["rounds"])
