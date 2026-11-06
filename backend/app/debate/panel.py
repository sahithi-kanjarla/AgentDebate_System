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


_PRETTIER_WIDTH = 100  # frontend/.prettierrc printWidth


def _prettier_json(value: Any, indent: int = 0) -> str:
    """JSON laid out the way Prettier formats it (objects always expanded, arrays of scalars on
    one line when they fit), so `npm run format:check` passes on the generated file."""
    pad = "  " * indent
    inner = "  " * (indent + 1)
    if isinstance(value, dict):
        if not value:
            return "{}"
        items = [
            f"{inner}{json.dumps(k)}: {_prettier_json(v, indent + 1)}" for k, v in value.items()
        ]
        return "{\n" + ",\n".join(items) + f"\n{pad}}}"
    if isinstance(value, list):
        if not value:
            return "[]"
        if not any(isinstance(v, dict | list) for v in value):
            flat = "[" + ", ".join(json.dumps(v, ensure_ascii=False) for v in value) + "]"
            if len(pad) + len(flat) + 1 <= _PRETTIER_WIDTH:  # +1 for a trailing comma
                return flat
        items = [f"{inner}{_prettier_json(v, indent + 1)}" for v in value]
        return "[\n" + ",\n".join(items) + f"\n{pad}]"
    return json.dumps(value, ensure_ascii=False)


def render(panel: dict[str, Any]) -> str:
    return _prettier_json(panel) + "\n"


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT
    # newline="\n": LF on every OS, as Prettier expects.
    with out.open("w", encoding="utf-8", newline="\n") as f:
        f.write(render(build_panel()))
    print(f"wrote {out}")
