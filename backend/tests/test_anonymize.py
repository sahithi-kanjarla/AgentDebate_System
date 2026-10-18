import pytest

from app.debate.anonymize import anonymize

PEERS = [f"debater_{i}" for i in range(1, 7)]


def test_same_seed_is_deterministic():
    a = anonymize("debater_1", PEERS, seed=42, round_=1)
    b = anonymize("debater_1", PEERS, seed=42, round_=1)
    assert a.order == b.order


def test_input_order_does_not_matter():
    a = anonymize("debater_1", PEERS, seed=7, round_=2)
    b = anonymize("debater_1", list(reversed(PEERS)), seed=7, round_=2)
    assert a.order == b.order


def test_shuffle_varies_with_seed_round_and_recipient():
    base = anonymize("debater_1", PEERS, seed=42, round_=1).order
    assert any(anonymize("debater_1", PEERS, seed=s, round_=1).order != base for s in range(10))
    assert any(anonymize("debater_1", PEERS, seed=42, round_=r).order != base for r in range(2, 12))
    others = [anonymize(f"debater_{i}", PEERS, seed=42, round_=1).order for i in range(2, 7)]
    assert len({tuple(o) for o in others}) > 1


def test_recipient_is_excluded_from_its_own_peers():
    anon = anonymize("debater_3", PEERS, seed=1, round_=1)
    assert "debater_3" not in anon.order and len(anon.order) == 5


@pytest.mark.parametrize("seed,round_", [(1, 1), (42, 2), (99, 3)])
def test_mapping_round_trips_to_the_right_agent(seed, round_):
    anon = anonymize("debater_2", PEERS, seed=seed, round_=round_)
    assert sorted(anon.mapping.values()) == sorted(p for p in PEERS if p != "debater_2")
    for label, agent in anon.mapping.items():
        assert anon.resolve(label) == agent
        assert anon.label_for(agent) == label


def test_resolve_is_tolerant_and_rejects_unknown():
    anon = anonymize("debater_1", ["debater_2", "debater_3"], seed=1, round_=1)
    assert anon.resolve("response 2") == anon.order[1]
    assert anon.resolve("Response #1") == anon.order[0]
    assert anon.resolve("Response 3") is None
    assert anon.resolve("Response 0") is None
    assert anon.resolve("the third one") is None
