from pathlib import Path
from string import Template

from app.providers.base import Message

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"
USER_MARKER = "<!-- user -->"


def _read(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


def render_messages(name: str, **values: object) -> list[Message]:
    """Render prompts/<name>.md into [system, user] messages (split at the user marker)."""
    system, user = _read(name).split(USER_MARKER, 1)
    fields = {k: str(v) for k, v in values.items()}
    return [
        Message(role="system", content=Template(system.strip()).safe_substitute(fields)),
        Message(role="user", content=Template(user.strip()).safe_substitute(fields)),
    ]


def mode_task(mode: str) -> str:
    return _read(f"mode_{mode}").strip()
