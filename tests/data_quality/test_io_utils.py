from __future__ import annotations

import pytest

from llmops.data.io_utils import count_lines, read_jsonl, write_jsonl


def test_round_trip(tmp_path):
    p = tmp_path / "x.jsonl"
    records = [{"id": str(i), "v": i} for i in range(5)]
    n = write_jsonl(p, records)
    assert n == 5
    assert count_lines(p) == 5
    assert list(read_jsonl(p)) == records


def test_skips_blank_lines(tmp_path):
    p = tmp_path / "x.jsonl"
    p.write_text('{"a":1}\n\n  \n{"a":2}\n', encoding="utf-8")
    assert [r["a"] for r in read_jsonl(p)] == [1, 2]


def test_raises_on_malformed(tmp_path):
    p = tmp_path / "bad.jsonl"
    p.write_text('{"a":1}\nnot-json\n', encoding="utf-8")
    with pytest.raises(ValueError, match="invalid JSON"):
        list(read_jsonl(p))


def test_raises_on_non_object(tmp_path):
    p = tmp_path / "arr.jsonl"
    p.write_text("[1,2]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="expected object"):
        list(read_jsonl(p))


def test_count_lines_nonexistent(tmp_path):
    assert count_lines(tmp_path / "nope.jsonl") == 0
