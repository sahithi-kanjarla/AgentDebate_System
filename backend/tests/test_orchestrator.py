import asyncio

import pytest

from app.core.settings import load_agents
from app.debate.orchestrator import Orchestrator
from app.providers.base import CompletionResult, LLMProvider, Message
from app.providers.demo_script import DEMO_SCRIPTS
from app.providers.mock import JUDGE, MockProvider, MockScript, MockTurn
from app.providers.registry import build_provider
from app.schemas import DebateEvent


def make(
    overrides: dict[str, LLMProvider | MockScript] | None = None,
    rounds: int = 3,
    min_critique_rounds: int = 1,
):
    agents = load_agents()
    providers: dict[str, LLMProvider] = {}
    for cfg in [*agents.debaters, agents.judge]:
        ov = (overrides or {}).get(cfg.id)
        if isinstance(ov, LLMProvider):
            providers[cfg.id] = ov
        else:
            providers[cfg.id] = build_provider(cfg, ov)
    return Orchestrator(
        debate_id="t1",
        question="What is 17 * 24?",
        mode="answer",
        rounds=rounds,
        agents=agents,
        providers=providers,
        seed=42,
        min_critique_rounds=min_critique_rounds,
    )


async def collect(orch: Orchestrator):
    return [event async for event in orch.run()]


def types(events):
    return [t for t, _ in events]


def of_type(events, kind):
    return [d for t, d in events if t == kind]


def answer(value: str, confidence: int = 90) -> MockTurn:
    return MockTurn(output={"reasoning": "r", "final_answer": value, "confidence": confidence})


def unanimous_script(value: str = "42") -> MockScript:
    return MockScript(turns={0: answer(value)}, default=answer(value))


class CrashingProvider(LLMProvider):
    def __init__(self, exc: Exception) -> None:
        self.exc = exc
        self.calls = 0

    async def complete(self, messages: list[Message], json_mode: bool = True) -> CompletionResult:
        self.calls += 1
        raise self.exc


async def test_default_demo_debate_story():
    orch = make()
    events = await collect(orch)

    assert types(events)[0] == "debate_started" and types(events)[-2:] == ["judge_verdict", "done"]
    assert [d["agents"] for d in of_type(events, "debate_started")][0] == [
        {"label": "Debater 1", "persona": "Solver"},
        {"label": "Debater 2", "persona": "Skeptic"},
        {"label": "Debater 3", "persona": "Fact-Checker"},
    ]

    rounds = of_type(events, "round_complete")
    assert [r["round"] for r in rounds] == [0, 1]  # stopped early after consensus in round 1
    assert not rounds[0]["agreed"] and rounds[0]["consensus_score"] == pytest.approx(2 / 3)
    assert rounds[1]["agreed"] and rounds[1]["consensus_score"] == 1.0

    # Debater 3 starts wrong, is critiqued by both others, changes its mind.
    r0 = {d["agent"]: d["payload"] for d in of_type(events, "agent_response") if d["round"] == 0}
    assert r0["Debater 3"]["final_answer"] == "398"
    edges = of_type(events, "critique_edge")
    assert sorted((e["from_agent"], e["to_agent"]) for e in edges) == [
        ("Debater 1", "Debater 3"),
        ("Debater 2", "Debater 3"),
    ]
    assert all(e["severity"] == "high" and e["round"] == 1 for e in edges)
    r1 = {d["agent"]: d["payload"] for d in of_type(events, "agent_response") if d["round"] == 1}
    assert r1["Debater 3"]["changed_mind"] and r1["Debater 3"]["changed_mind_because"]
    assert r1["Debater 3"]["final_answer"] == "408"
    assert r1["Debater 3"]["cluster_id"] == r1["Debater 1"]["cluster_id"]
    assert r0["Debater 3"]["cluster_id"] != r0["Debater 1"]["cluster_id"]

    verdict = of_type(events, "judge_verdict")[0]["payload"]
    assert verdict["final_answer"] == "408" and verdict["mistakes_caught"]
    assert orch.verdict is not None and orch.verdict.final_answer == "408"
    # 3 debaters x 2 rounds + judge
    assert of_type(events, "done")[0]["stats"]["calls"] == 7
    assert len([t for t in orch.turns if t.valid]) == 7


async def test_critique_edge_follows_matching_agent_response():
    events = await collect(make())
    for i, (kind, data) in enumerate(events):
        if kind == "critique_edge":
            before = events[i - 1]
            assert before[0] in ("agent_response", "critique_edge")
            assert before[1].get("agent", data["from_agent"]) == data["from_agent"]


async def test_events_are_valid_debate_events_with_json_safe_data():
    events = await collect(make())
    for seq, (kind, data) in enumerate(events):
        DebateEvent(seq=seq, type=kind, data=data).model_dump_json()


async def test_unanimous_round_zero_still_runs_a_critique_round():
    scripts = {c: unanimous_script() for c in ("debater_1", "debater_2", "debater_3")}
    events = await collect(make(scripts))
    rounds = of_type(events, "round_complete")
    assert [r["round"] for r in rounds] == [0, 1]  # min_critique_rounds=1 forces round 1
    assert all(r["agreed"] for r in rounds)
    r1 = [d for d in of_type(events, "agent_response") if d["round"] == 1]
    assert len(r1) == 3 and all(d["payload"]["valid"] for d in r1)
    assert types(events)[-2:] == ["judge_verdict", "done"]


async def test_min_critique_rounds_zero_allows_stopping_after_round_zero():
    scripts = {c: unanimous_script() for c in ("debater_1", "debater_2", "debater_3")}
    events = await collect(make(scripts, min_critique_rounds=0))
    assert [r["round"] for r in of_type(events, "round_complete")] == [0]


async def test_min_critique_rounds_is_capped_by_rounds():
    scripts = {c: unanimous_script() for c in ("debater_1", "debater_2", "debater_3")}
    events = await collect(make(scripts, rounds=1, min_critique_rounds=3))
    assert [r["round"] for r in of_type(events, "round_complete")] == [0, 1]


async def test_min_critique_rounds_two_runs_two_rounds():
    scripts = {c: unanimous_script() for c in ("debater_1", "debater_2", "debater_3")}
    events = await collect(make(scripts, min_critique_rounds=2))
    assert [r["round"] for r in of_type(events, "round_complete")] == [0, 1, 2]


async def test_max_rounds_respected_without_consensus():
    disagree = {f"debater_{i}": MockScript(turns={}, default=answer(str(i))) for i in (1, 2, 3)}
    events = await collect(make(disagree, rounds=2))
    assert [r["round"] for r in of_type(events, "round_complete")] == [0, 1, 2]
    assert not of_type(events, "round_complete")[-1]["agreed"]


async def test_event_order_within_round():
    events = await collect(make())
    first_round = []
    for kind, _data in events:
        first_round.append(kind)
        if kind == "round_complete":
            break
    assert first_round[:4] == [
        "debate_started",
        "agent_thinking",
        "agent_thinking",
        "agent_thinking",
    ]
    assert first_round[-1] == "round_complete"
    assert first_round.count("agent_response") == 3


@pytest.mark.parametrize(
    "exc",
    [RuntimeError("provider exploded"), ValueError("bad"), KeyError("k")],
    ids=["runtime", "value", "key"],
)
async def test_one_agent_crash_does_not_cancel_the_others(exc):
    # Debater 2 raises immediately; Debater 1 is slow and must still finish; Debater 3 too.
    crasher = CrashingProvider(exc)
    slow = DEMO_SCRIPTS["debater_1"]()
    for turn in (*slow.turns.values(), slow.default):
        turn.delay_s = 0.05
    orch = make({"debater_2": crasher, "debater_1": slow})
    events = await collect(orch)

    # The crashing agent produced an error + invalid turn in every round it was asked.
    errors = of_type(events, "error")
    assert errors and all(e["agent"] == "Debater 2" and e["recoverable"] for e in errors)
    invalid = [d for d in of_type(events, "agent_response") if not d["payload"]["valid"]]
    assert {d["agent"] for d in invalid} == {"Debater 2"}

    # The others completed round 0 and the debate reached a verdict.
    r0 = {d["agent"] for d in of_type(events, "agent_response") if d["round"] == 0}
    assert r0 == {"Debater 1", "Debater 2", "Debater 3"}
    valid_r0 = {
        d["agent"]
        for d in of_type(events, "agent_response")
        if d["round"] == 0 and d["payload"]["valid"]
    }
    assert valid_r0 == {"Debater 1", "Debater 3"}
    assert types(events)[-2:] == ["judge_verdict", "done"]
    assert orch.verdict is not None
    assert crasher.calls >= 1
    # Crashed agent counts against the denominator: never 3/3.
    assert all(r["consensus_score"] < 1.0 for r in of_type(events, "round_complete"))


async def test_crash_in_a_later_round_keeps_earlier_work():
    script = DEMO_SCRIPTS["debater_3"]()
    script.turns[1] = MockTurn(error="rate limited")
    orch = make({"debater_3": script})
    events = await collect(orch)
    errors = of_type(events, "error")
    assert [(e["agent"], e["message"]) for e in errors] == [("Debater 3", "rate limited")]
    valid = [t for t in orch.turns if t.agent_id == "debater_3" and t.valid]
    assert [t.round for t in valid] == [0]
    assert types(events)[-1] == "done"


async def test_all_agents_failing_still_ends_with_a_verdict():
    boom = {f"debater_{i}": CrashingProvider(RuntimeError("x")) for i in (1, 2, 3)}
    events = await collect(make(boom, rounds=1))
    assert types(events)[-2:] == ["judge_verdict", "done"]


async def test_malformed_json_twice_marks_turn_invalid_and_continues():
    bad = MockScript(turns={0: MockTurn(output="not json at all")}, default=answer("408"))
    orch = make({"debater_2": bad})
    events = await collect(orch)
    r0 = {d["agent"]: d["payload"] for d in of_type(events, "agent_response") if d["round"] == 0}
    assert r0["Debater 2"]["valid"] is False
    assert any(t.agent_id == "debater_2" and not t.valid for t in orch.turns)
    assert types(events)[-1] == "done"


async def test_malformed_then_repaired_json_is_valid():
    good = {"reasoning": "r", "final_answer": "408", "confidence": 80}
    fixed = MockScript(
        turns={0: MockTurn(output="{oops", repair_output=good)}, default=answer("408")
    )
    events = await collect(make({"debater_2": fixed}))
    r0 = {d["agent"]: d["payload"] for d in of_type(events, "agent_response") if d["round"] == 0}
    assert r0["Debater 2"]["valid"] is True
    assert of_type(events, "error") == []


async def test_judge_failure_falls_back_to_majority_verdict():
    judge = MockScript(turns={JUDGE: MockTurn(error="judge down")})
    orch = make({"judge": judge})
    events = await collect(orch)
    errors = of_type(events, "error")
    assert errors[-1]["agent"] == "Judge" and errors[-1]["message"] == "judge down"
    verdict = of_type(events, "judge_verdict")[0]["payload"]
    assert verdict["final_answer"] == "408" and verdict["consensus_reached"]
    assert "unavailable" in verdict["summary"]
    assert types(events)[-1] == "done"


async def test_prompts_never_leak_provider_or_model_names():
    seen: list[str] = []

    class Spy(MockProvider):
        async def complete(self, messages, json_mode=True):
            seen.extend(m.content for m in messages)
            return await super().complete(messages, json_mode)

    agents = load_agents()
    spies = {c.id: Spy(DEMO_SCRIPTS[c.id]()) for c in [*agents.debaters, agents.judge]}
    await collect(make(spies))
    blob = "\n".join(seen).lower()
    for cfg in [*agents.debaters, agents.judge]:
        assert cfg.model.lower() not in blob
    assert "response 1:" in blob and "debater 3" in blob


async def test_round_agents_run_concurrently():
    # Three agents each sleeping 0.4s in round 0: sequentially that alone would take >= 1.2s.
    scripts = {}
    for i in (1, 2, 3):
        s = unanimous_script()
        s.turns[0].delay_s = 0.4
        scripts[f"debater_{i}"] = s
    orch = make(scripts)
    start = asyncio.get_running_loop().time()
    await collect(orch)
    assert asyncio.get_running_loop().time() - start < 0.9
