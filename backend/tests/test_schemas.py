import pytest
from pydantic import ValidationError

from app.schemas import CreateDebateRequest, DebaterOutput


def test_debater_output_defaults():
    out = DebaterOutput(reasoning="r", final_answer="42", confidence=80)
    assert out.critiques == [] and out.changed_mind is False and out.changed_mind_because is None


@pytest.mark.parametrize("confidence", [-1, 101])
def test_confidence_bounds(confidence):
    with pytest.raises(ValidationError):
        DebaterOutput(reasoning="r", final_answer="42", confidence=confidence)


def test_bad_severity_rejected():
    with pytest.raises(ValidationError):
        DebaterOutput(
            reasoning="r",
            final_answer="1",
            confidence=1,
            critiques=[{"target": "Response 1", "issue": "x", "severity": "critical"}],
        )


@pytest.mark.parametrize(
    "kwargs", [{"question": ""}, {"question": "x" * 4001}, {"question": "q", "rounds": 4}]
)
def test_request_validation(kwargs):
    with pytest.raises(ValidationError):
        CreateDebateRequest(**kwargs)
