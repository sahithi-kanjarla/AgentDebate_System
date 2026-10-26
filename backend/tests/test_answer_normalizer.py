"""The optional answer normaliser on the orchestrator (used by multiple-choice evals)."""

from app.core.settings import load_agents
from app.debate.orchestrator import Orchestrator
from app.providers.base import LLMProvider
from app.providers.mock import MockScript
from app.providers.registry import build_provider
from tests.conftest import MOCK_AGENTS
from tests.test_orchestrator import answer, collect, make, of_type


def letter(text: str) -> str:
    return text.strip().strip("().").upper()


def build(normalizer, scripts: dict[str, MockScript]) -> Orchestrator:
    agents = load_agents(MOCK_AGENTS)
    providers: dict[str, LLMProvider] = {
        cfg.id: build_provider(cfg, scripts.get(cfg.id)) for cfg in [*agents.debaters, agents.judge]
    }
    return Orchestrator(
        debate_id="t1",
        question="Pick one.",
        mode="answer",
        rounds=3,
        agents=agents,
        providers=providers,
        seed=42,
        answer_normalizer=normalizer,
    )


def spellings() -> dict[str, MockScript]:
    return {
        "debater_1": MockScript(turns={0: answer("(B).")}, default=answer("B")),
        "debater_2": MockScript(turns={0: answer("b")}, default=answer("(b)")),
        "debater_3": MockScript(turns={0: answer("B")}, default=answer("B.")),
        "judge": MockScript(turns={}, default=answer("(B).")),
    }


async def test_default_leaves_answers_exactly_as_the_model_wrote_them():
    orch = make({"debater_1": MockScript(turns={0: answer("(B).")}, default=answer("(B)."))})
    events = await collect(orch)
    first = [d for d in of_type(events, "agent_response") if d["round"] == 0][0]
    assert first["payload"]["final_answer"] in {"(B).", "42"}
    assert all("final_answer_raw" not in d["payload"] for d in of_type(events, "agent_response"))


async def test_different_spellings_cluster_and_the_debate_stops_early():
    orch = build(letter, spellings())
    events = await collect(orch)
    rounds = of_type(events, "round_complete")
    # round 0 already agrees on B, and the app's minimum of one critique round still runs
    assert rounds[0]["agreed"] is True and rounds[-1]["round"] == 1
    assert {t.parsed_json["final_answer"] for t in orch.turns if t.label != "Judge"} == {"B"}
    raw = {t.parsed_json.get("final_answer_raw") for t in orch.turns if t.round == 0}
    assert raw == {"(B).", "b", None}  # kept where the model's text was changed
    assert orch.verdict is not None and orch.verdict.final_answer == "B"


async def test_the_normalised_form_is_what_peers_and_the_judge_see():
    orch = build(letter, spellings())
    await collect(orch)
    transcript = orch._transcript()
    assert "final answer B (confidence" in transcript
    assert "(B)." not in transcript
