"""Structured JSON logging with contextvars and a secret scrubber.

Log records never carry prompts or responses. As a second line of defence the formatter
replaces any configured API key and any `Bearer ...` token with [REDACTED].
"""

import contextvars
import json
import logging
import re
import sys
from collections.abc import Iterable
from datetime import UTC, datetime

debate_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "debate_id", default=None
)
agent_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("agent", default=None)

# Attributes of a stock LogRecord; anything else came in through `extra=`.
_STANDARD = set(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {"message", "asctime"}
_BEARER = re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+")
_HANDLER_MARK = "_tribunal_json_handler"


def scrub_text(text: str, secrets: Iterable[str]) -> str:
    """Replace every configured secret and any `Bearer ...` token with [REDACTED]."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return _BEARER.sub("Bearer [REDACTED]", text)


class JsonFormatter(logging.Formatter):
    def __init__(self, secrets: Iterable[str] = ()) -> None:
        super().__init__()
        self._secrets = [s for s in secrets if s]

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        if (d := debate_id_var.get()) is not None:
            payload["debate_id"] = d
        if (a := agent_var.get()) is not None:
            payload["agent"] = a
        for key, value in vars(record).items():
            if key not in _STANDARD and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
        return self.scrub(json.dumps(payload, default=str, ensure_ascii=False))

    def scrub(self, text: str) -> str:
        return scrub_text(text, self._secrets)


def configure_logging(level: str = "INFO", secrets: Iterable[str] = ()) -> None:
    """Install the JSON handler on the `app` logger (idempotent)."""
    logger = logging.getLogger("app")
    for h in list(logger.handlers):
        if getattr(h, _HANDLER_MARK, False):
            logger.removeHandler(h)
    handler = logging.StreamHandler(sys.stderr)
    setattr(handler, _HANDLER_MARK, True)
    handler.setFormatter(JsonFormatter(secrets))
    logger.addHandler(handler)
    logger.setLevel(level.upper())
