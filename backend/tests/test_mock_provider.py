import json

import pytest

from app.core.settings import load_agents
from app.providers.base import Message, ProviderError
from app.providers.mock import MockProvider, MockScript, MockTurn
from app.providers.registry import build_provider
from app.schemas import DebaterOutput, JudgeOutput


def debater_msgs(round_: int, peers: dict[int, str] | None = None) -> list[Message]:
    body = f"ROLE: debater\nROUND: {round_}\n"
    for n, ans in (peers or {}).items():
        body += f"Response {n}:\nsome reasoning\nFinal answer: {ans}\n"
    return [Message(role="user", content=body)]


async def test_demo_story_wrong_agent_changes_mind():
    cfg = load_agents()
    d1, d3 = (build_provider(c) for c in (cfg.debaters[0], cfg.debaters[2]))
    r0 = DebaterOutput.model_validate_json((await d1.complete(debater_msgs(0))).text)
    assert r0.final_answer == "408"
    wrong = DebaterOutput.model_validate_json((await d3.complete(debater_msgs(0))).text)
    assert wrong.final_answer == "398"
    fixed = DebaterOutput.model_validate_json(
        (await d3.complete(debater_msgs(1, {1: "408", 2: "408"}))).text
    )
    assert fixed.changed_mind and fixed.final_answer == "408" and fixed.changed_mind_because


@pytest.mark.parametrize(
    "peers,expected",
    [({1: "408", 2: "398"}, "Response 2"), ({1: "398", 2: "408"}, "Response 1")],
)
async def test_critique_target_survives_shuffle(peers, expected):
    d1 = build_provider(load_agents().debaters[0])
    out = DebaterOutput.model_validate_json((await d1.complete(debater_msgs(1, peers))).text)
    assert [c.target for c in out.critiques] == [expected]


async def test_critique_dropped_when_nobody_holds_target_answer():
    d1 = build_provider(load_agents().debaters[0])
    out = DebaterOutput.model_validate_json(
        (await d1.complete(debater_msgs(1, {1: "408", 2: "408"}))).text
    )
    assert out.critiques == []


async def test_judge_output_valid():
    judge = build_provider(load_agents().judge)
    msgs = [Message(role="user", content="ROLE: judge\ntranscript")]
    out = JudgeOutput.model_validate_json((await judge.complete(msgs)).text)
    assert out.consensus_reached and out.mistakes_caught[0].caught_by == "Debater 1"


async def test_malformed_then_repair():
    good = {"reasoning": "r", "final_answer": "1", "confidence": 5}
    p = MockProvider(MockScript(turns={0: MockTurn(output="{not json", repair_output=good)}))
    first = await p.complete(debater_msgs(0))
    with pytest.raises(json.JSONDecodeError):
        json.loads(first.text)
    repair = debater_msgs(0) + [Message(role="user", content="Please FIX YOUR JSON")]
    assert json.loads((await p.complete(repair)).text)["final_answer"] == "1"


async def test_scripted_error_and_missing_turn():
    p = MockProvider(MockScript(turns={0: MockTurn(error="boom")}))
    with pytest.raises(ProviderError, match="boom"):
        await p.complete(debater_msgs(0))
    with pytest.raises(ProviderError):
        await p.complete(debater_msgs(2))


def test_unknown_provider_rejected():
    cfg = load_agents().debaters[0].model_copy(update={"provider": "nope"})
    with pytest.raises(ValueError):
        build_provider(cfg)
