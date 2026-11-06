"""The public description of the panel, generated from the agents config for the landing page.

The landing page names the models. It deliberately does NOT say which model sits in which debater
slot, so the "Show which model was which" reveal still tells the visitor something. Models are
listed alphabetically, personas separately. Regenerate the committed file after changing the config:

    uv run python -m app.debate.panel ../frontend/public/panel.json
"""

import json
import sys
from pathlib import Path
from typing import Any

import yaml

from app.core.settings import BACKEND_DIR

PANEL_FORMAT = 1
DEFAULT_CONFIG = BACKEND_DIR / "config" / "agents.yaml"
DEFAULT_OUTPUT = BACKEND_DIR.parent / "frontend" / "public" / "panel.json"

# Model id (after any "org/" prefix) -> the lab that trained it. The provider is only the host:
# Groq serves OpenAI's open-weight models, for example.
_LABS: tuple[tuple[str, str], ...] = (
    ("gemini", "Google"),
    ("gemma", "Google"),
    ("gpt-", "OpenAI"),
    ("ministral", "Mistral AI"),
    ("mistral", "Mistral AI"),
    ("llama", "Meta"),
    ("qwen", "Alibaba"),
    ("deepseek", "DeepSeek"),
)


def lab_for(model: str) -> str:
    bare = model.rsplit("/", 1)[-1].lower()
    for prefix, lab in _LABS:
        if bare.startswith(prefix):
            return lab
    return "Unknown"


def build_panel(config_path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    debaters = cfg["debaters"]
    judge = cfg["judge"]
    models = sorted({d["model"] for d in debaters})
    return {
        "format": PANEL_FORMAT,
        "debaters": [{"model": m, "lab": lab_for(m)} for m in models],
        "personas": [d["persona"] for d in debaters],
        "judge": {"model": judge["model"], "lab": lab_for(judge["model"])},
        "judge_shares_model_with_a_debater": judge["model"] in models,
    }


def render(panel: dict[str, Any]) -> str:
    return json.dumps(panel, indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT
    out.write_text(render(build_panel()), encoding="utf-8")
    print(f"wrote {out}")
