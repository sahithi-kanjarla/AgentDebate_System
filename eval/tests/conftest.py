"""Offline guarantees for the eval tests: no network, no real keys (same fixtures as the app)."""

import pytest

from app.core.settings import BACKEND_DIR, Settings
from tests.conftest import no_network, no_real_keys  # noqa: F401

MOCK_AGENTS = BACKEND_DIR / "config" / "agents.mock.yaml"


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'unused.db'}",
        agents_config=MOCK_AGENTS,
        _env_file=None,
    )
