"""Server-side withholding of provider, model and label_map, and the reveal endpoint."""

import json
import re

from sqlmodel import Session, select

from app.db import repo
from app.db.models import Debate, Turn
from app.debate.public import strip_hidden
from tests.conftest import MOCK_AGENTS, demo_factory, parse_sse, wait_until

BANNED_KEYS = {"label_map", "provider", "model"}


def config_terms(path) -> set[str]:
    """Provider and model names from a config file, so no name is typed into a test."""
    text = path.read_text(encoding="utf-8")
    # Block style (`model: x`) and the inline fallback style (`{provider: x, model: "y"}`).
    pattern = r"\b(?:provider|model)\s*:\s*['\"]?([^\s#'\",}]+)"
    return {m.group(1) for m in re.finditer(pattern, text)}


def keys_in(value):
    """Every dict key in a value, at any depth."""
    if isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from keys_in(v)
    elif isinstance(value, list):
        for v in value:
            yield from keys_in(v)


def assert_anonymous(raw: str, terms: set[str]) -> None:
    if raw.lstrip().startswith(("{", "[")):
        assert not BANNED_KEYS & set(keys_in(json.loads(raw))), "hidden key present"
    lowered = raw.lower()
    assert "label_map" not in lowered
    for term in terms:
        assert term.lower() not in lowered, f"{term!r} leaked"


async def finished(client, app, **body) -> str:
    resp = await client.post("/api/debates", json={"question": "What is 17 * 24?", **body})
    debate_id = resp.json()["id"]
    await client.get(f"/api/debates/{debate_id}/stream")
    await wait_until(lambda: debate_id not in app.state.service._channels)
    return debate_id


def test_strip_hidden_is_recursive_and_does_not_mutate():
    original = {"a": [{"model": "m", "keep": 1, "x": {"label_map": {}, "provider": "p"}}]}
    assert strip_hidden(original) == {"a": [{"keep": 1, "x": {}}]}
    assert "model" in original["a"][0]  # the input is untouched


async def test_every_debate_endpoint_is_anonymous(make_client):
    terms = config_terms(MOCK_AGENTS)
    assert "mock-solver" in terms
    async with make_client() as (client, app):
        debate_id = await finished(client, app)
        replay = await client.get(f"/api/debates/{debate_id}/stream")
        assert_anonymous(replay.text, terms)
        resume = await client.get(
            f"/api/debates/{debate_id}/stream", headers={"Last-Event-ID": "3"}
        )
        assert_anonymous(resume.text, terms)
        for url in (f"/api/debates/{debate_id}", "/api/debates?limit=5"):
            assert_anonymous((await client.get(url)).text, terms)
        agents = await client.get("/api/agents")  # the public view, the default
        assert_anonymous(agents.text, terms)
        assert set(agents.json()[0]) == {"id", "role", "persona", "status", "reachable"}


async def test_live_stream_is_anonymous_while_running(make_client):
    terms = config_terms(MOCK_AGENTS)
    async with make_client(demo_factory(delay_s=0.02)) as (client, _):
        resp = await client.post("/api/debates", json={"question": "What is 17 * 24?"})
        debate_id = resp.json()["id"]
        live = await client.get(f"/api/debates/{debate_id}/stream")
        assert_anonymous(live.text, terms)
        assert parse_sse(live.text)[-1]["event"] == "done"


async def test_data_is_kept_in_the_database_and_event_log(make_client):
    """Withholding happens when serving: the stored log still carries label_map and the models."""
    async with make_client() as (client, app):
        debate_id = await finished(client, app)
        engine = app.state.service.engine
        rows = repo.get_events(engine, debate_id)
        full = repo.get_debate(engine, debate_id)
    assert any("label_map" in json.dumps(r["data"]) for r in rows)
    assert {t["model"] for t in full["turns"]} >= {"mock-solver", "mock-judge"}


async def test_expose_agent_models_flag_restores_the_full_agents_listing(make_client):
    async with make_client(expose_agent_models=True) as (client, _):
        agents = (await client.get("/api/agents")).json()
    assert agents[0]["provider"] == "mock" and agents[0]["model"] == "mock-solver"


async def test_reveal_returns_per_debater_models_and_the_judge(make_client):
    async with make_client() as (client, app):
        debate_id = await finished(client, app)
        resp = await client.get(f"/api/debates/{debate_id}/reveal")
    assert resp.status_code == 200
    body = resp.json()
    assert "label_map" not in resp.text
    assert [d["label"] for d in body["debaters"]] == ["Debater 1", "Debater 2", "Debater 3"]
    d1 = body["debaters"][0]
    assert d1["persona"] == "Solver"
    assert d1["primary"] == {"provider": "mock", "model": "mock-solver"}
    assert [t["round"] for t in d1["turns"]] == [0, 1]
    assert all(t["fallback_used"] is False for t in d1["turns"])
    assert body["judge"]["label"] == "Judge"
    assert body["judge"]["primary"]["model"] == "mock-judge"
    assert "never told each other's identity" in body["note"]


async def test_reveal_reports_which_turns_a_fallback_answered(make_client):
    async with make_client() as (client, app):
        debate_id = await finished(client, app)
        with Session(app.state.service.engine) as s:
            turn = s.exec(
                select(Turn).where(Turn.debate_id == debate_id, Turn.agent_label == "Debater 2")
            ).first()
            turn.fallback_used, turn.provider, turn.model = True, "other", "other-model"
            s.add(turn)
            s.commit()
        body = (await client.get(f"/api/debates/{debate_id}/reveal")).json()
    d2 = body["debaters"][1]
    assert [(t["provider"], t["fallback_used"]) for t in d2["turns"]] == [
        ("other", True),
        ("mock", False),
    ]
    # One fallback turn out of two does not rename the debater: the earliest wins a tie.
    assert d2["primary"]["provider"] == "other"


async def test_reveal_is_409_while_running_then_available(make_client):
    async with make_client(demo_factory(delay_s=0.05)) as (client, app):
        resp = await client.post("/api/debates", json={"question": "What is 17 * 24?"})
        debate_id = resp.json()["id"]
        assert (await client.get(f"/api/debates/{debate_id}/reveal")).status_code == 409
        await wait_until(lambda: debate_id not in app.state.service._channels)
        assert (await client.get(f"/api/debates/{debate_id}/reveal")).status_code == 200


async def test_reveal_of_unknown_debate_is_404(make_client):
    async with make_client() as (client, _):
        assert (await client.get("/api/debates/nope/reveal")).status_code == 404


async def test_reveal_works_for_an_interrupted_debate(make_client):
    async with make_client() as (client, app):
        debate_id = await finished(client, app)
        with Session(app.state.service.engine) as s:
            d = s.get(Debate, debate_id)
            d.status = "interrupted"
            s.add(d)
            s.commit()
        assert (await client.get(f"/api/debates/{debate_id}/reveal")).status_code == 200
