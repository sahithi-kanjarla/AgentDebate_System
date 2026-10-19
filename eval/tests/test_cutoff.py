"""The cut-off heuristic looks at every reply of a turn, not only the last one."""

import math

from app.debate.orchestrator import TurnRecord
from app.debate.parsing import Attempt
from eval.runner import looks_truncated

LIMIT = 4096


def turn(attempts, *, valid=False, raw_text="{}", error="invalid output after repair: x"):
    return TurnRecord(
        round=0,
        agent_id="debater_1",
        label="Debater 1",
        persona="Solver",
        provider="gemini",
        model="m",
        prompt_hash="h",
        raw_text=raw_text,
        parsed_json=None,
        valid=valid,
        tokens_in=1,
        tokens_out=sum(a.tokens_out for a in attempts),
        latency_ms=1,
        error=error,
        attempts=attempts,
    )


def test_a_cut_off_first_reply_counts_although_the_repair_reply_is_complete():
    # Q371 Gemini round 0: 4092 of 4096 tokens, then a complete (but unparseable) repair reply.
    t = turn([Attempt(None, 4092, False), Attempt(None, 310, False)])
    assert looks_truncated(t, LIMIT)


def test_stored_finish_reason_length_counts_on_any_reply():
    assert looks_truncated(turn([Attempt("length", 100, False), Attempt("stop", 90, False)]), LIMIT)


def test_stored_finish_reason_stop_overrides_the_token_check():
    # Ended on its own just under the limit: not cut off when the provider said "stop".
    assert not looks_truncated(turn([Attempt("stop", 4090, False)]), LIMIT)


def test_unbalanced_braces_in_the_first_reply_count():
    assert looks_truncated(turn([Attempt(None, 500, True), Attempt(None, 400, False)]), LIMIT)


def test_short_complete_replies_and_a_missing_limit_do_not_count():
    short = turn([Attempt(None, 500, False), Attempt(None, 400, False)])
    assert not looks_truncated(short, LIMIT)
    assert not looks_truncated(turn([Attempt(None, 4092, False)]), None)  # limit unknown


def test_threshold_is_95_percent_of_the_limit():
    edge = math.ceil(LIMIT * 0.95)  # 3892
    assert looks_truncated(turn([Attempt(None, edge, False)]), LIMIT)
    assert not looks_truncated(turn([Attempt(None, edge - 1, False)]), LIMIT)


def test_a_valid_turn_is_never_cut_off():
    assert not looks_truncated(turn([Attempt("length", 4096, True)], valid=True), LIMIT)


def test_provider_error_with_finish_reason_length_still_counts():
    t = turn([], raw_text="", error="empty_response (finish_reason=length)")
    assert looks_truncated(t, LIMIT)
