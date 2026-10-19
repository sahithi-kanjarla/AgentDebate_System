import io
import json

import pytest

from eval.datasets import GSM8K, DatasetError, get_dataset, load_order, order_path
from eval.tests.helpers import write_gsm8k


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_loads_questions_with_stable_ids(tmp_path):
    ds = write_gsm8k(tmp_path / "t.jsonl", 3)
    qs = ds.load()
    assert [q.qid for q in qs] == ["gsm8k-test-0", "gsm8k-test-1", "gsm8k-test-2"]
    assert ds.score(qs[1], "11").correct and not ds.score(qs[1], "12").correct
    assert ds.gold_label(qs[1]) == "11"
    assert ds.prompt(qs[0]).endswith("Give the final answer as a plain number with no units.")


def test_missing_file_says_how_to_fetch(tmp_path):
    with pytest.raises(DatasetError, match="eval.datasets fetch"):
        GSM8K(tmp_path / "nope.jsonl").load()


def test_order_is_seeded_stored_and_prefix_stable(tmp_path):
    ds = write_gsm8k(tmp_path / "t.jsonl", 20)
    order = load_order(ds, 42, tmp_path)
    assert sorted(order) == sorted(q.qid for q in ds.load())
    assert order != [q.qid for q in ds.load()]  # actually shuffled
    assert load_order(ds, 42, tmp_path) == order  # read back from the stored file
    assert order_path("gsm8k", 42, tmp_path).exists()
    assert load_order(ds, 7, tmp_path) != order  # another seed, another order


def test_stored_order_is_refused_when_the_data_changed(tmp_path):
    ds = write_gsm8k(tmp_path / "t.jsonl", 5)
    load_order(ds, 42, tmp_path)
    write_gsm8k(tmp_path / "t.jsonl", 6)
    with pytest.raises(DatasetError, match="does not match"):
        load_order(ds, 42, tmp_path)


def test_fetch_uses_an_injected_opener_and_never_the_network(tmp_path):
    body = (json.dumps({"question": "q", "answer": "x\n#### 1"}) + "\n").encode()
    urls = []

    def opener(url, timeout):
        urls.append(url)
        return Resp(body)

    ds = GSM8K(tmp_path / "d" / "t.jsonl")
    assert ds.fetch(opener) == 1
    assert urls[0].startswith("https://raw.githubusercontent.com/openai/grade-school-math")
    assert len(ds.load()) == 1


def test_fetch_rejects_a_file_that_is_not_gsm8k(tmp_path):
    ds = GSM8K(tmp_path / "t.jsonl")
    with pytest.raises(DatasetError):
        ds.fetch(lambda url, timeout: Resp(b"[]\n"))
    assert not ds.path.exists()


def test_unknown_dataset():
    with pytest.raises(DatasetError):
        get_dataset("nope")
