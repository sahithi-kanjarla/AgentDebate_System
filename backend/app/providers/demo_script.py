"""Default demo debate: 17 x 24.

Debater 3 answers 398 (wrong), is critiqued by the other two in round 1, changes its mind, and
the debate reaches consensus on 408.
"""

from app.providers.mock import JUDGE, MockScript, MockTurn

CORRECT = "408"
WRONG = "398"


def _unchanged(confidence: int) -> MockTurn:
    return MockTurn(
        output={"reasoning": "Unchanged.", "final_answer": CORRECT, "confidence": confidence}
    )


def _debater_1() -> MockScript:
    return MockScript(
        turns={
            0: MockTurn(
                output={
                    "reasoning": "17 x 24 = 17 x 20 + 17 x 4 = 340 + 68 = 408.",
                    "final_answer": CORRECT,
                    "confidence": 92,
                }
            ),
            1: MockTurn(
                output={
                    "reasoning": "Re-checked: 340 + 68 = 408. The 398 answer is off by 10.",
                    "critiques": [
                        {
                            "target_answer": WRONG,
                            "issue": "17 x 4 is 68, not 58, so 340 + 68 = 408, not 398.",
                            "severity": "high",
                        }
                    ],
                    "final_answer": CORRECT,
                    "confidence": 97,
                }
            ),
        },
        default=_unchanged(97),
    )


def _debater_2() -> MockScript:
    return MockScript(
        turns={
            0: MockTurn(
                output={
                    "reasoning": "24 x 17 = 24 x 10 + 24 x 7 = 240 + 168 = 408.",
                    "final_answer": CORRECT,
                    "confidence": 85,
                }
            ),
            1: MockTurn(
                output={
                    "reasoning": "Verified by a second decomposition; 408 holds.",
                    "critiques": [
                        {
                            "target_answer": WRONG,
                            "issue": "Arithmetic slip: 24 x 17 is 408; 398 fits no decomposition.",
                            "severity": "high",
                        }
                    ],
                    "final_answer": CORRECT,
                    "confidence": 95,
                }
            ),
        },
        default=_unchanged(95),
    )


def _debater_3() -> MockScript:
    return MockScript(
        turns={
            0: MockTurn(
                output={
                    "reasoning": "17 x 24 = 340 + 58 = 398.",
                    "final_answer": WRONG,
                    "confidence": 70,
                }
            ),
            1: MockTurn(
                output={
                    "reasoning": "Redoing it: 17 x 4 = 68, not 58. So 340 + 68 = 408.",
                    "critiques": [],
                    "changed_mind": True,
                    "changed_mind_because": (
                        "Two peers pointed out that 17 x 4 = 68, which makes the sum 408."
                    ),
                    "final_answer": CORRECT,
                    "confidence": 88,
                }
            ),
        },
        default=_unchanged(88),
    )


def _judge() -> MockScript:
    return MockScript(
        turns={
            JUDGE: MockTurn(
                output={
                    "final_answer": CORRECT,
                    "confidence": 96,
                    "summary": (
                        "Two debaters independently reached 408. The third answered 398 because "
                        "of a slip (17 x 4 = 58), was critiqued, and corrected itself."
                    ),
                    "mistakes_caught": [
                        {
                            "description": "Debater 3 computed 17 x 4 as 58, giving 398 not 408.",
                            "caught_by": "Debater 1",
                            "round": 1,
                        }
                    ],
                    "dissent": None,
                    "consensus_reached": True,
                }
            )
        }
    )


DEMO_SCRIPTS = {
    "debater_1": _debater_1,
    "debater_2": _debater_2,
    "debater_3": _debater_3,
    "judge": _judge,
}
