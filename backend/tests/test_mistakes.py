"""Server-built mistakes_caught and received_critiques."""

from app.debate.mistakes import CritiqueRecord, build_mistakes_caught, received_critiques
from app.providers.mock import JUDGE, MockScript, MockTurn
from tests.test_orchestrator import collect, make, of_type

LABELS = ["Debater 1", "Debater 2", "Debater 3"]


def crit(rnd, critic, target, issue="issue", severity="high"):
    return CritiqueRecord(rnd, critic, target, severity, issue)


# --- the rule, unit by unit ---


def test_catch_requires_a_wrong_target_and_a_critic_who_matches_the_verdict():
    answers = {
        0: {"Debater 1": "408", "Debater 2": "398"},
        1: {"Debater 1": "408", "Debater 2": "408"},
    }
    got = build_mistakes_caught("408", [crit(1, "Debater 1", "Debater 2", "17x4 is 68")], answers)
    assert [(m.description, m.caught_by, m.round) for m in got] == [("17x4 is 68", "Debater 1", 1)]


def test_a_critic_who_was_wrong_at_the_time_is_not_credited():
    answers = {0: {"Debater 1": "A", "Debater 2": "B"}, 1: {"Debater 1": "A", "Debater 2": "B"}}
    # Debater 2 still held B in round 1 (it switched to the verdict only later).
    assert build_mistakes_caught("A", [crit(1, "Debater 2", "Debater 1")], answers) == []
    answers[1]["Debater 2"] = "C"
    assert build_mistakes_caught("A", [crit(1, "Debater 2", "Debater 3")], answers) == []


def test_critiquing_an_answer_equal_to_the_verdict_catches_nothing():
    answers = {0: {"Debater 1": "A", "Debater 2": "A"}, 1: {"Debater 1": "A", "Debater 2": "A"}}
    assert build_mistakes_caught("A", [crit(1, "Debater 1", "Debater 2")], answers) == []


def test_numbers_compare_by_value_everything_else_exactly():
    answers = {0: {"Debater 2": "408.0"}, 1: {"Debater 1": "408"}}
    assert build_mistakes_caught("408", [crit(1, "Debater 1", "Debater 2")], answers) == []
    # Known limitation: a textually different but equivalent answer is a false catch.
    answers = {0: {"Debater 2": "[1,2]"}, 1: {"Debater 1": "[1, 2]"}}
    assert len(build_mistakes_caught("[1, 2]", [crit(1, "Debater 1", "Debater 2")], answers)) == 1


def test_first_catcher_wins_per_target_and_wrong_answer():
    answers = {
        0: {"Debater 1": "A", "Debater 2": "A", "Debater 3": "B"},
        1: {"Debater 1": "A", "Debater 2": "A", "Debater 3": "B"},
        2: {"Debater 1": "A", "Debater 2": "A", "Debater 3": "A"},
    }
    got = build_mistakes_caught(
        "A",
        [
            crit(1, "Debater 1", "Debater 3", "first"),
            crit(1, "Debater 2", "Debater 3", "second"),
            crit(2, "Debater 2", "Debater 3", "third"),  # D3 still held B before round 2
        ],
        answers,
    )
    assert [(m.description, m.caught_by, m.round) for m in got] == [("first", "Debater 1", 1)]


def test_a_new_wrong_answer_from_the_same_target_is_a_new_catch():
    answers = {
        0: {"Debater 1": "A", "Debater 3": "B"},
        1: {"Debater 1": "A", "Debater 3": "C"},
        2: {"Debater 1": "A", "Debater 3": "A"},
    }
    got = build_mistakes_caught(
        "A",
        [crit(1, "Debater 1", "Debater 3", "b"), crit(2, "Debater 1", "Debater 3", "c")],
        answers,
    )
    assert [(m.description, m.round) for m in got] == [("b", 1), ("c", 2)]


def test_missing_answers_and_self_critiques_are_skipped():
    answers = {0: {"Debater 1": "A"}, 1: {"Debater 1": "A"}}
    records = [
        crit(1, "Debater 1", "Debater 2"),  # target never gave a valid answer
        crit(1, "Debater 3", "Debater 1"),  # critic has no answer this round
        crit(1, "Debater 1", "Debater 1"),
    ]
    assert build_mistakes_caught("A", records, answers) == []


def test_a_wrong_verdict_credits_critics_of_the_right_answer():
    """Known limitation, kept visible: the list is only as good as the verdict."""
    answers = {0: {"Debater 1": "right", "Debater 2": "wrong"}, 1: {"Debater 2": "wrong"}}
    got = build_mistakes_caught("wrong", [crit(1, "Debater 2", "Debater 1")], answers)
    assert [m.caught_by for m in got] == ["Debater 2"]


def test_received_critiques_groups_by_target_and_gives_every_agent_a_key():
    got = received_critiques(
        [crit(1, "Debater 1", "Debater 3", "x", "low"), crit(1, "Debater 2", "Debater 3", "y")],
        LABELS,
    )
    assert got["Debater 1"] == [] and got["Debater 2"] == []
    assert got["Debater 3"] == [
        {"from_agent": "Debater 1", "issue": "x", "severity": "low", "round": 1},
        {"from_agent": "Debater 2", "issue": "y", "severity": "high", "round": 1},
    ]


# --- the Python mutable-default-argument debate, replayed ---

RIGHT = "[1] [1, 2] [1, 2, 3]"  # what Python prints
SPACED = "[1] [1,2] [1,2,3]"  # right idea, wrong spacing: a different answer
OTHER = "[1, 2, 3]"


def turn(answer, *critiques):
    return MockTurn(
        output={
            "reasoning": "r",
            "final_answer": answer,
            "confidence": 85,
            "critiques": [
                {"target_answer": target, "issue": issue, "severity": "high"}
                for target, issue in critiques
            ],
        }
    )


def mutable_default_scripts():
    d1 = MockScript(
        turns={
            0: turn(RIGHT),
            1: turn(
                RIGHT,
                (SPACED, "Python prints a space after each comma"),
                (OTHER, "the default list is shared, so earlier calls leak into later ones"),
            ),
        },
        default=turn(RIGHT),
    )
    d2 = MockScript(
        turns={
            0: turn(SPACED),
            1: turn(
                SPACED,
                (RIGHT, "the default list is recreated on every call"),  # wrong at the time
                (OTHER, "that ignores the earlier calls"),  # critic is still wrong in round 1
            ),
            2: turn(RIGHT, (OTHER, "late repeat of the same point")),  # right now, but a duplicate
        },
        default=turn(RIGHT),
    )
    d3 = MockScript(
        turns={
            0: turn(OTHER),
            1: turn(OTHER, (RIGHT, "each call starts with an empty list"), (SPACED, "no spaces")),
        },
        default=turn(RIGHT),
    )
    judge = MockScript(
        turns={
            JUDGE: MockTurn(
                output={
                    "final_answer": RIGHT,
                    "confidence": 90,
                    "summary": "Debater 1 was right from the start.",
                    "dissent": None,
                    "consensus_reached": True,
                    # The judge's own list is wrong and must be ignored.
                    "mistakes_caught": [
                        {"description": "bogus", "caught_by": "Debater 2", "round": 1},
                        {"description": "bogus", "caught_by": "Debater 2", "round": 1},
                    ],
                }
            )
        }
    )
    return {"debater_1": d1, "debater_2": d2, "debater_3": d3, "judge": judge}


async def test_mutable_default_argument_debate_credits_only_the_debater_who_was_right():
    orch = make(mutable_default_scripts(), rounds=3)
    events = await collect(orch)

    rounds = of_type(events, "round_complete")
    assert [r["round"] for r in rounds] == [0, 1, 2]
    assert [len(r["clusters"]) for r in rounds] == [3, 3, 1]  # exact: spacing makes a cluster
    assert rounds[2]["agreed"]

    verdict = of_type(events, "judge_verdict")[0]["payload"]
    assert verdict["final_answer"] == RIGHT
    assert verdict["summary"] == "Debater 1 was right from the start."  # the judge's prose stays
    caught = verdict["mistakes_caught"]
    assert [(m["caught_by"], m["round"]) for m in caught] == [("Debater 1", 1), ("Debater 1", 1)]
    assert [m["description"] for m in caught] == [
        "Python prints a space after each comma",
        "the default list is shared, so earlier calls leak into later ones",
    ]
    assert orch.verdict is not None and orch.verdict.model_dump() == verdict
    judge_turn = orch.turns[-1]
    assert (
        judge_turn.parsed_json is not None and judge_turn.parsed_json["mistakes_caught"] == caught
    )


async def test_received_critiques_are_filled_in_at_round_close():
    orch = make(mutable_default_scripts(), rounds=3)
    events = await collect(orch)
    r0, r1, r2 = of_type(events, "round_complete")

    assert r0["received_critiques"] == {}  # no critiques in round 0
    got = r1["received_critiques"]
    assert set(got) == set(LABELS)
    assert [(c["from_agent"], c["severity"], c["round"]) for c in got["Debater 2"]] == [
        ("Debater 1", "high", 1),
        ("Debater 3", "high", 1),
    ]
    assert [c["issue"] for c in got["Debater 2"]] == [
        "Python prints a space after each comma",
        "no spaces",
    ]
    assert [c["from_agent"] for c in got["Debater 1"]] == ["Debater 2", "Debater 3"]
    assert [c["from_agent"] for c in r2["received_critiques"]["Debater 3"]] == ["Debater 2"]

    # Stored on the turn, but not smuggled into the already-emitted agent_response event.
    d2_r1 = next(t for t in orch.turns if t.label == "Debater 2" and t.round == 1)
    assert (
        d2_r1.parsed_json is not None
        and d2_r1.parsed_json["received_critiques"] == got["Debater 2"]
    )
    event = next(
        d
        for d in of_type(events, "agent_response")
        if d["agent"] == "Debater 2" and d["round"] == 1
    )
    assert "received_critiques" not in event["payload"]


async def test_fallback_verdict_gets_the_same_server_built_list():
    judge_down = MockScript(turns={JUDGE: MockTurn(error="judge down")})
    events = await collect(make({"judge": judge_down}))
    verdict = of_type(events, "judge_verdict")[0]["payload"]
    assert verdict["final_answer"] == "408"
    assert [(m["caught_by"], m["round"]) for m in verdict["mistakes_caught"]] == [("Debater 1", 1)]
