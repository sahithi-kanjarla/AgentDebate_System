import asyncio
import io
import json
import logging
import socket
from pathlib import Path

import pytest

from app.core.logging import JsonFormatter, agent_var, configure_logging, debate_id_var
from app.core.settings import REPO_ROOT, Settings, load_agents
from tests.conftest import REAL_AGENTS
from tests.fakes import FAKE_KEY, MSGS, error_response, make_provider, ok_response


@pytest.fixture
def log_lines():
    """Capture the `app` logger's JSON output, scrubbing FAKE_KEY like production does."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter([FAKE_KEY]))
    logger = logging.getLogger("app")
    old_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    yield lambda: [json.loads(line) for line in stream.getvalue().splitlines() if line]
    logger.removeHandler(handler)
    logger.setLevel(old_level)


async def test_llm_call_is_logged_with_structured_fields(log_lines):
    p = make_provider(lambda r: ok_response(), name="groq", model="some-model")
    await p.complete(MSGS)
    (rec,) = [r for r in log_lines() if r["event"] == "llm_call"]
    assert rec["provider"] == "groq" and rec["model"] == "some-model" and rec["status"] == "ok"
    assert rec["tokens_in"] == 11 and rec["tokens_out"] == 7
    assert rec["attempts"] == 1 and rec["retries"] == 0 and rec["latency_ms"] >= 0
    assert rec["level"] == "INFO" and "ts" in rec


async def test_retries_and_failures_are_logged(log_lines):
    p = make_provider(lambda r: error_response(503))
    with pytest.raises(Exception, match="server_error"):
        await p.complete(MSGS)
    records = log_lines()
    retries = [r for r in records if r["event"] == "llm_retry"]
    assert len(retries) == 2 and retries[0]["error_category"] == "server_error"
    (call,) = [r for r in records if r["event"] == "llm_call"]
    assert call["status"] == "error" and call["attempts"] == 3 and call["retries"] == 2
    assert call["http_status"] == 503


async def test_logs_never_contain_prompts_responses_or_keys(log_lines):
    p = make_provider(lambda r: ok_response("SECRET-RESPONSE-TEXT"))
    await p.complete(MSGS)
    failing = make_provider(lambda r: error_response(400, f"bad {FAKE_KEY} SECRET-PROMPT-TEXT"))
    with pytest.raises(Exception, match="bad_request"):
        await failing.complete(MSGS)
    blob = json.dumps(log_lines())
    for forbidden in (FAKE_KEY, "SECRET-PROMPT-TEXT", "SECRET-RESPONSE-TEXT"):
        assert forbidden not in blob


def test_formatter_scrubs_keys_and_bearer_tokens_even_if_logged_by_mistake(log_lines):
    log = logging.getLogger("app.test")
    log.info("oops %s", FAKE_KEY, extra={"header": f"Authorization: Bearer {FAKE_KEY}", "n": 1})
    log.info("another", extra={"auth": "Bearer abc.DEF-123_xyz"})
    blob = json.dumps(log_lines())
    assert FAKE_KEY not in blob and "abc.DEF-123_xyz" not in blob
    assert "[REDACTED]" in blob


async def test_context_vars_are_attached(log_lines):
    debate_id_var.set("d-123")
    agent_var.set("Debater 2")
    logging.getLogger("app.test").info("hello")
    (rec,) = [r for r in log_lines() if r["event"] == "hello"]
    assert rec["debate_id"] == "d-123" and rec["agent"] == "Debater 2"


def test_configure_logging_is_idempotent():
    configure_logging("INFO", ["x"])
    configure_logging("INFO", ["x"])
    handlers = [
        h for h in logging.getLogger("app").handlers if getattr(h, "_tribunal_json_handler", False)
    ]
    assert len(handlers) == 1
    logging.getLogger("app").removeHandler(handlers[0])


# --- settings & secrets hygiene ---


def test_keys_are_secret_strings_and_blank_means_unset():
    s = Settings(
        gemini_api_key="test-key-123", groq_api_key="", openrouter_api_key="  ", _env_file=None
    )
    assert s.api_key("gemini_api_key") == "test-key-123"
    assert s.api_key("groq_api_key") is None and s.api_key("openrouter_api_key") is None
    assert s.api_key(None) is None
    assert "test-key-123" not in repr(s) and "test-key-123" not in str(s)
    assert s.secret_values() == ["test-key-123"]


def test_env_example_lists_the_three_keys_empty():
    lines = (REPO_ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    values = dict(line.split("=", 1) for line in lines if "=" in line and not line.startswith("#"))
    for name in ("GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY"):
        assert values.get(name) == ""


def test_gitignore_covers_env_files_and_databases():
    ignored = (Path(REPO_ROOT) / ".gitignore").read_text(encoding="utf-8").split()
    assert ".env" in ignored and "*.db" in ignored


def test_real_agents_config_is_valid_and_has_no_secrets():
    cfg = load_agents(REAL_AGENTS)
    assert {a.provider for a in cfg.all_agents()} <= set(cfg.providers)
    text = REAL_AGENTS.read_text(encoding="utf-8")
    assert (
        "api_key:" not in text
        and "AIza" not in text
        and "gsk_" not in text
        and "sk-or-" not in text
    )
    # every agent has at least one local fallback so a debate works with no keys at all
    assert all(any(f.provider == "ollama" for f in a.fallbacks) for a in cfg.all_agents())


def test_unknown_provider_reference_is_rejected(tmp_path):
    bad = tmp_path / "agents.yaml"
    bad.write_text(
        "debaters:\n  - {id: d, persona: P, provider: nope, model: m}\n"
        "judge: {id: j, persona: J, provider: mock, model: m}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown provider"):
        load_agents(bad)


# --- the network guard itself ---


def test_network_guard_blocks_real_hosts():
    with pytest.raises(RuntimeError, match="network access blocked"):
        socket.getaddrinfo("api.groq.com", 443)
    with pytest.raises(RuntimeError, match="network access blocked"):
        socket.socket().connect(("93.184.216.34", 443))


async def test_network_guard_blocks_asyncio_connections():
    with pytest.raises(RuntimeError, match="network access blocked"):
        await asyncio.get_running_loop().create_connection(asyncio.Protocol, "api.groq.com", 443)
