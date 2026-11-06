import asyncio
import hashlib
import time

import pytest
from sqlalchemy import text
from sqlmodel import Session

from app.db import repo
from app.db.models import Debate
from app.db.session import init_db, make_engine
from app.providers.base import LLMProvider
from tests.conftest import demo_factory, parse_sse, wait_until

EXPECTED_TYPES = (
    ["debate_started"]
    + ["agent_thinking"] * 3
    + ["agent_response"] * 3
    + ["round_complete"]
    + ["agent_thinking"] * 3
    + ["agent_response", "critique_edge", "agent_response", "critique_edge", "agent_response"]
    + ["round_complete", "agent_thinking", "judge_verdict", "done"]
)


CLIENT_A = {"X-Client-Id": "a" * 32}
CLIENT_B = {"X-Client-Id": "b" * 32}


async def create(client, headers=None, **body) -> str:
    resp = await client.post(
        "/api/debates", json={"question": "What is 17 * 24?", **body}, headers=headers
    )
    assert resp.status_code == 201
    return resp.json()["id"]


async def stream(client, debate_id: str, **headers) -> list[dict]:
    resp = await client.get(f"/api/debates/{debate_id}/stream", headers=headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    return parse_sse(resp.text)


async def test_health_and_agents(make_client):
    async with make_client(expose_agent_models=True) as (client, _):
        assert (await client.get("/api/health")).json() == {"status": "ok"}
        agents = (await client.get("/api/agents")).json()
        assert [a["role"] for a in agents] == ["debater"] * 3 + ["judge"]
        assert all(a["reachable"] for a in agents) and agents[0]["model"] == "mock-solver"


async def test_post_then_stream_full_event_sequence(make_client):
    async with make_client() as (client, _):
        debate_id = await create(client)
        events = await stream(client, debate_id)
    assert [e["event"] for e in events] == EXPECTED_TYPES
    assert [e["id"] for e in events] == list(range(len(events)))  # contiguous seq as SSE id
    assert events[-1]["data"]["stats"]["calls"] == 7


async def test_stored_transcript_event_log_and_turns(make_client):
    async with make_client() as (client, _):
        debate_id = await create(client)
        live = await stream(client, debate_id)
        await wait_until(lambda: True)
        got = (await client.get(f"/api/debates/{debate_id}")).json()

    assert got["status"] == "completed" and got["mode"] == "answer"
    assert got["verdict"]["final_answer"] == "408"
    assert got["stats"]["calls"] == 7
    # The persisted ordered event log equals what was streamed live.
    assert [(e["seq"], e["type"], e["data"]) for e in got["events"]] == [
        (e["id"], e["event"], e["data"]) for e in live
    ]
    # 3 debaters x 2 rounds + judge, with replay data in parsed_json.
    assert len(got["turns"]) == 7
    d3 = [t for t in got["turns"] if t["agent_label"] == "Debater 3"]
    assert [t["round"] for t in d3] == [0, 1]
    assert d3[1]["parsed_json"]["changed_mind_because"] and "cluster_id" in d3[1]["parsed_json"]
    assert all(t["valid"] for t in got["turns"])


async def test_stream_after_completion_replays_from_the_db(make_client):
    async with make_client() as (client, app):
        debate_id = await create(client)
        first = await stream(client, debate_id)
        await wait_until(lambda: debate_id not in app.state.service._channels)
        again = await stream(client, debate_id)
    assert again == first


async def test_last_event_id_resumes_after_that_event(make_client):
    async with make_client() as (client, app):
        debate_id = await create(client)
        full = await stream(client, debate_id)
        await wait_until(lambda: debate_id not in app.state.service._channels)
        resumed = await stream(client, debate_id, **{"Last-Event-ID": "10"})
    assert [e["id"] for e in resumed] == [e["id"] for e in full if e["id"] > 10]


async def test_client_connecting_mid_debate_gets_replay_then_live(make_client):
    async with make_client(demo_factory(delay_s=0.05)) as (client, app):
        debate_id = await create(client)
        channel = app.state.service._channels[debate_id]
        await wait_until(lambda: len(channel.events) >= 6)  # clearly mid-debate
        assert not channel.finished
        already = len(channel.events)

        events = await stream(client, debate_id)  # joins late; returns when `done` arrives
    assert already < len(events)  # some events were live, the rest replayed
    assert [e["event"] for e in events] == EXPECTED_TYPES  # nothing missed or duplicated
    assert [e["id"] for e in events] == list(range(len(events)))


async def test_many_clients_see_the_same_stream(make_client):
    async with make_client(demo_factory(delay_s=0.02)) as (client, _):
        debate_id = await create(client)
        a, b = await asyncio.gather(stream(client, debate_id), stream(client, debate_id))
    assert a == b and [e["event"] for e in a] == EXPECTED_TYPES


async def test_rounds_and_review_mode_are_stored(make_client):
    async with make_client() as (client, _):
        debate_id = await create(client, mode="review", rounds=1)
        await stream(client, debate_id)
        got = (await client.get(f"/api/debates/{debate_id}")).json()
    assert got["mode"] == "review" and got["config"]["rounds"] == 1


async def test_min_critique_rounds_setting_flows_through(make_client):
    from app.providers.mock import MockProvider, MockScript, MockTurn

    def unanimous(agents):
        turn = MockTurn(output={"reasoning": "r", "final_answer": "42", "confidence": 90})
        providers: dict[str, LLMProvider] = {
            c.id: MockProvider(MockScript(turns={0: turn}, default=turn)) for c in agents.debaters
        }
        providers["judge"] = demo_factory()(agents)["judge"]
        return providers

    async with make_client(unanimous) as (client, _):
        events = await stream(client, await create(client))
    rounds = [e["data"]["round"] for e in events if e["event"] == "round_complete"]
    assert rounds == [0, 1]  # unanimous in round 0, but a critique round still runs

    async with make_client(unanimous, min_critique_rounds=0) as (client, _):
        events = await stream(client, await create(client))
    rounds = [e["data"]["round"] for e in events if e["event"] == "round_complete"]
    assert rounds == [0]


@pytest.mark.parametrize(
    "body",
    [
        {"question": ""},
        {"question": "   "},
        {"question": "x" * 4001},
        {"question": "q", "rounds": 0},
        {"question": "q", "rounds": 4},
        {"question": "q", "mode": "chat"},
        {},
    ],
)
async def test_invalid_requests_rejected(make_client, body):
    async with make_client() as (client, _):
        assert (await client.post("/api/debates", json=body)).status_code == 422


async def test_question_at_the_limit_is_accepted(make_client):
    async with make_client() as (client, _):
        assert (await client.post("/api/debates", json={"question": "x" * 4000})).status_code == 201


async def test_unknown_debate_is_404(make_client):
    async with make_client() as (client, _):
        assert (await client.get("/api/debates/nope")).status_code == 404
        assert (await client.get("/api/debates/nope/stream")).status_code == 404


async def test_history_lists_recent_debates_newest_first(make_client):
    async with make_client() as (client, app):
        ids = []
        for q in ("first?", "second?", "third?"):
            ids.append(await create(client, CLIENT_A, question=q))
            await stream(client, ids[-1])
            await wait_until(lambda: not app.state.service._channels)
            await asyncio.sleep(0.01)
        listing = (await client.get("/api/debates?limit=2", headers=CLIENT_A)).json()
        assert [d["id"] for d in listing] == [ids[2], ids[1]]
        assert listing[0]["final_answer"] == "408" and listing[0]["status"] == "completed"
        assert (await client.get("/api/debates?limit=0", headers=CLIENT_A)).status_code == 422


async def test_history_is_private_to_each_client_id(make_client):
    async with make_client() as (client, _):
        a_id = await create(client, CLIENT_A, question="mine?")
        b_id = await create(client, CLIENT_B, question="yours?")
        anon_id = await create(client, question="nobody's?")
        a = (await client.get("/api/debates", headers=CLIENT_A)).json()
        b = (await client.get("/api/debates", headers=CLIENT_B)).json()
    assert [d["id"] for d in a] == [a_id]
    assert [d["id"] for d in b] == [b_id]
    assert anon_id not in {d["id"] for d in a + b}


async def test_history_without_a_usable_client_id_is_empty(make_client):
    async with make_client() as (client, _):
        await create(client, CLIENT_A)
        assert (await client.get("/api/debates")).json() == []
        for bad in ("", "short", "x" * 200, "has spaces and !! " * 3):
            resp = await client.get("/api/debates", headers={"X-Client-Id": bad})
            assert resp.json() == []


async def test_debates_stay_open_by_id_for_any_client(make_client):
    async with make_client() as (client, _):
        debate_id = await create(client, CLIENT_A)
        events = await stream(client, debate_id, **CLIENT_B)
        assert events[-1]["event"] == "done"
        await wait_until(lambda: True)
        assert (await client.get(f"/api/debates/{debate_id}", headers=CLIENT_B)).status_code == 200
        assert (await client.get(f"/api/debates/{debate_id}")).status_code == 200
        assert (await client.get(f"/api/debates/{debate_id}/stream")).status_code == 200


async def test_only_a_hash_of_the_client_id_is_stored(make_client):
    async with make_client() as (client, app):
        debate_id = await create(client, CLIENT_A)
        await stream(client, debate_id)
        with Session(app.state.service.engine) as s:
            row = s.get(Debate, debate_id)
    expected = hashlib.sha256(CLIENT_A["X-Client-Id"].encode()).hexdigest()
    assert row.owner_hash == expected
    assert CLIENT_A["X-Client-Id"] not in (row.owner_hash or "")


def test_init_db_adds_owner_hash_to_an_old_database_and_keeps_its_rows(tmp_path):
    url = f"sqlite:///{tmp_path / 'old.db'}"
    old = make_engine(url)
    with old.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE debate (id VARCHAR PRIMARY KEY, question VARCHAR, mode VARCHAR, "
                "status VARCHAR, created_at DATETIME, config_json JSON, verdict_json JSON, "
                "stats_json JSON)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO debate (id, question, mode, status, created_at, config_json) "
                "VALUES ('old1', 'q?', 'answer', 'completed', '2026-01-01 00:00:00', '{}')"
            )
        )
    old.dispose()

    engine = make_engine(url)
    init_db(engine)
    init_db(engine)  # safe to run on every start
    assert repo.debate_exists(engine, "old1")
    assert repo.get_debate(engine, "old1")["question"] == "q?"
    digest = hashlib.sha256(b"c" * 32).hexdigest()
    assert repo.list_debates(engine, 20, digest) == []
    repo.create_debate(
        engine, debate_id="new1", question="n?", mode="answer", config={}, owner_hash=digest
    )
    assert [d["id"] for d in repo.list_debates(engine, 20, digest)] == ["new1"]
    engine.dispose()


async def test_unfinished_debates_are_marked_interrupted_on_startup(make_client, settings):
    async with make_client(demo_factory(delay_s=0.5)) as (client, app):
        debate_id = await create(client)
        await wait_until(lambda: len(app.state.service._channels[debate_id].events) >= 2)
    # Leaving the context cancelled the run; a fresh app on the same DB sees it as interrupted.
    async with make_client() as (client, _):
        got = (await client.get(f"/api/debates/{debate_id}")).json()
        assert got["status"] == "interrupted"
        replay = await stream(client, debate_id)
        assert replay and replay[0]["event"] == "debate_started"


async def test_db_writes_do_not_block_the_event_loop(make_client, monkeypatch):
    real = repo.append_event

    def slow_append(*args, **kwargs):
        time.sleep(0.3)  # a blocking DB call; fine on a worker thread, fatal on the loop
        return real(*args, **kwargs)

    monkeypatch.setattr(repo, "append_event", slow_append)
    gaps: list[float] = []

    async def ticker(stop: asyncio.Event) -> None:
        loop = asyncio.get_running_loop()
        last = loop.time()
        while not stop.is_set():
            await asyncio.sleep(0.01)
            now = loop.time()
            gaps.append(now - last)
            last = now

    async with make_client() as (client, app):
        # Warm up cold code paths (imports, first queries) so only DB blocking can stall the loop.
        await stream(client, await create(client))
        await wait_until(lambda: not app.state.service._channels)
        gaps.clear()
        stop = asyncio.Event()
        tick = asyncio.create_task(ticker(stop))
        debate_id = await create(client)
        events = await stream(client, debate_id)
        stop.set()
        await tick
    assert events[-1]["event"] == "done" and len(gaps) > 10
    assert max(gaps) < 0.2, f"event loop stalled for {max(gaps):.3f}s"


async def test_unexpected_orchestrator_failure_still_ends_the_stream(make_client, monkeypatch):
    from app.debate import orchestrator

    async def broken_run(self):
        yield "debate_started", {"id": self.debate_id, "agents": []}
        raise RuntimeError("bug in orchestrator")

    monkeypatch.setattr(orchestrator.Orchestrator, "run", broken_run)
    async with make_client() as (client, app):
        debate_id = await create(client)
        events = await stream(client, debate_id)
        await wait_until(lambda: not app.state.service._channels)
        got = (await client.get(f"/api/debates/{debate_id}")).json()
    assert [e["event"] for e in events] == ["debate_started", "error", "done"]
    assert events[1]["data"]["recoverable"] is False
    assert got["status"] == "failed"
