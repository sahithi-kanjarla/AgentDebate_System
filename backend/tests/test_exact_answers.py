"""Exact final answers and server-derived changed_mind, end to end (mock providers only)."""

import pytest

from app.core.settings import load_agents
from app.db.session import init_db, make_engine
from app.debate.prompts import PROMPTS_DIR, render_messages
from app.providers.base import Message
from app.providers.cached import CachedProvider
from app.providers.mock import JUDGE, MockProvider, MockScript, MockTurn
from tests.conftest import REAL_AGENTS, wait_until
from tests.fakes import MSGS, StubProvider
from tests.test_orchestrator import collect, make, of_type, unanimous_script


def reply(value: str, *, claims_changed: bool = False, because: str | None = None) -> MockTurn:
    return MockTurn(
        output={
            "reasoning": "r",
            "final_answer": value,
            "confidence": 80,
            "changed_mind": claims_changed,
            "changed_mind_because": because,
        }
    )


def by_agent(events, round_):
    return {
        d["agent"]: d["payload"] for d in of_type(events, "agent_response") if d["round"] == round_
    }


# --- changed_mind is derived from the answer clusters, not the model's claim ---


async def test_changed_mind_is_derived_and_the_models_claim_is_kept_separately():
    d1 = MockScript(
        turns={0: reply("A"), 1: reply("A", claims_changed=True, because="nothing")},
        default=reply("A"),
    )  # never changed, but says it did
    d2 = MockScript(turns={0: reply("B"), 1: reply("A", claims_changed=False)}, default=reply("A"))
    events = await collect(
        make({"debater_1": d1, "debater_2": d2, "debater_3": unanimous_script("A")})
    )

    r0, r1 = by_agent(events, 0), by_agent(events, 1)
    for label in r0:  # nobody has a previous answer in round 0
        assert r0[label]["changed_mind"] is False and r0[label]["previous_cluster_id"] is None
    assert r1["Debater 1"]["changed_mind"] is False
    assert r1["Debater 1"]["changed_mind_claimed"] is True
    assert r1["Debater 1"]["changed_mind_because"] == "nothing"  # the model's text is untouched
    assert r1["Debater 2"]["changed_mind"] is True  # moved B -> A
    assert r1["Debater 2"]["changed_mind_claimed"] is False
    assert r1["Debater 2"]["previous_cluster_id"] == r0["Debater 2"]["cluster_id"]
    assert r1["Debater 2"]["cluster_id"] != r1["Debater 2"]["previous_cluster_id"]
    assert (
        r1["Debater 3"]["changed_mind"] is False
        and r1["Debater 3"]["changed_mind_claimed"] is False
    )


async def test_numeric_respelling_is_not_a_change_but_a_whitespace_edit_is():
    d1 = MockScript(turns={0: reply("408"), 1: reply("408.0")}, default=reply("408.0"))
    d2 = MockScript(turns={0: reply("X"), 1: reply(" X")}, default=reply(" X"))
    events = await collect(
        make({"debater_1": d1, "debater_2": d2, "debater_3": unanimous_script("408")})
    )
    r1 = by_agent(events, 1)
    assert r1["Debater 1"]["changed_mind"] is False
    assert r1["Debater 2"]["changed_mind"] is True


async def test_derived_value_is_stored_and_used_in_the_judge_transcript():
    seen: list[str] = []

    class Spy(MockProvider):
        async def complete(self, messages, json_mode=True):
            seen.append("\n".join(m.content for m in messages))
            return await super().complete(messages, json_mode)

    d1 = MockScript(
        turns={0: reply("A"), 1: reply("A", claims_changed=True, because="CLAIMED-ONLY")},
        default=reply("A"),
    )
    d2 = MockScript(turns={0: reply("B"), 1: reply("A")}, default=reply("A"))
    judge = MockScript(turns={JUDGE: reply("A")})
    orch = make(
        {
            "debater_1": d1,
            "debater_2": d2,
            "debater_3": unanimous_script("A"),
            "judge": Spy(judge),
        }
    )
    await collect(orch)
    stored = {(t.label, t.round): t.parsed_json for t in orch.turns if t.agent_id != "judge"}
    assert stored[("Debater 2", 1)]["changed_mind"] is True
    assert stored[("Debater 1", 1)]["changed_mind"] is False
    assert stored[("Debater 1", 1)]["changed_mind_claimed"] is True
    transcript = seen[0]
    assert transcript.count("Changed answer from B") == 1  # only Debater 2 moved
    assert "CLAIMED-ONLY" not in transcript  # an unmoved agent's claim is not reported as fact


# --- whitespace in final_answer survives the whole pipeline ---


PADDED = " X "
INDENTED = "def f():\n    return 1\n"


async def test_leading_and_trailing_space_survive_the_round_trip(make_client):
    from tests.conftest import parse_sse

    def factory(agents):
        scripts = {c.id: unanimous_script(PADDED) for c in agents.debaters}
        verdict = {
            "final_answer": INDENTED,
            "confidence": 90,
            "summary": "s",
            "mistakes_caught": [],
            "consensus_reached": True,
        }
        scripts[agents.judge.id] = MockScript(turns={JUDGE: MockTurn(output=verdict)})
        return {i: MockProvider(s) for i, s in scripts.items()}

    async with make_client(factory) as (client, app):
        debate_id = (await client.post("/api/debates", json={"question": "q"})).json()["id"]
        live = parse_sse((await client.get(f"/api/debates/{debate_id}/stream")).text)
        await wait_until(lambda: debate_id not in app.state.service._channels)
        stored = (await client.get(f"/api/debates/{debate_id}")).json()

    responses = [e["data"]["payload"] for e in live if e["event"] == "agent_response"]
    assert responses and all(p["final_answer"] == PADDED for p in responses)
    clusters = [c for e in live if e["event"] == "round_complete" for c in e["data"]["clusters"]]
    assert clusters and all(c["normalized_answer"] == PADDED for c in clusters)
    assert [
        e["data"]["payload"]["final_answer"] for e in live if e["event"] == "judge_verdict"
    ] == [INDENTED]
    # Persisted turns, verdict and the stored event log carry the same exact strings.
    debaters = [t for t in stored["turns"] if t["agent_label"] != "Judge"]
    assert debaters and all(t["parsed_json"]["final_answer"] == PADDED for t in debaters)
    assert stored["verdict"]["final_answer"] == INDENTED
    logged = [e["data"] for e in stored["events"] if e["type"] == "agent_response"]
    assert all(d["payload"]["final_answer"] == PADDED for d in logged)


async def test_peers_see_the_exact_answer_in_the_next_round():
    seen: list[str] = []

    class Spy(MockProvider):
        async def complete(self, messages, json_mode=True):
            seen.append("\n".join(m.content for m in messages))
            return await super().complete(messages, json_mode)

    await collect(make({"debater_1": Spy(unanimous_script("[1, 2]"))}))
    assert any("Your previous answer: [1, 2] (confidence" in text for text in seen)


async def test_cache_returns_the_text_byte_for_byte(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'c.db'}")
    init_db(engine)
    exact = ' {"final_answer": " X "}\n'
    cached = CachedProvider(StubProvider("p", text=exact), engine)
    first, second = await cached.complete(MSGS), await cached.complete(MSGS)
    assert first.text == exact and second.text == exact and second.cached
    engine.dispose()


# --- prompts ---


def prompt_files():
    return sorted(PROMPTS_DIR.glob("*.md"))


@pytest.mark.parametrize("name", ["debater", "critique", "judge"])
def test_prompts_ask_for_the_bare_exact_answer(name):
    system = render_messages(name, persona="P", persona_prompt="pp")[0].content
    assert "ONLY the answer" in system or "only the answer" in system
    assert "short, normalized" not in system
    if name != "judge":
        assert "character for character" in system
        assert "exactly what the program would print" in system
        assert "preserving every" in system and "indent" in system
    else:
        assert "preserving" in system and "whitespace" in system


def test_no_prompt_names_a_model_or_provider():
    agents = load_agents(REAL_AGENTS)
    models = {a.model for a in agents.all_agents()} | {
        f.model for a in agents.all_agents() for f in a.fallbacks
    }
    banned = {m.lower() for m in models} | {
        "gemini",
        "groq",
        "openrouter",
        "ollama",
        "mistral",
        "gpt",
        "llama",
        "nemotron",
        "gemma",
        "openai",
        "anthropic",
        "claude",
    }
    for path in prompt_files():
        text = path.read_text(encoding="utf-8").lower()
        assert not [b for b in banned if b in text], path.name


def test_rendered_messages_keep_a_multiline_question_verbatim():
    question = "print('  X')\nprint('Y')"
    msgs = render_messages(
        "debater", persona="P", persona_prompt="", mode="answer", task="t", question=question
    )
    assert isinstance(msgs[1], Message) and question in msgs[1].content
