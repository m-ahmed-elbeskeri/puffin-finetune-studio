"""Record-level CRUD on JSONL files."""
from __future__ import annotations

import json

import pytest

from copilot.backend import data_records as dr


def _write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_read_records_window_and_total(repo):
    p = repo / "data" / "raw" / "d.jsonl"
    _write(p, [{"i": i} for i in range(10)])
    page = dr.read_records(repo, "data/raw/d.jsonl", offset=2, limit=3)
    assert page["total"] == 10
    assert [r["index"] for r in page["records"]] == [2, 3, 4]
    assert page["records"][0]["data"] == {"i": 2}


def test_read_flags_invalid_lines(repo):
    p = repo / "data" / "raw" / "bad.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"ok": 1}\nnot json\n{"ok": 2}\n', encoding="utf-8")
    page = dr.read_records(repo, "data/raw/bad.jsonl")
    assert page["total"] == 3
    assert page["records"][1]["valid"] is False
    assert "raw" in page["records"][1]


def test_append_update_delete(repo):
    p = repo / "data" / "raw" / "d.jsonl"
    _write(p, [{"i": 0}, {"i": 1}])

    r = dr.append_record(repo, "data/raw/d.jsonl", {"i": 2})
    assert r["total"] == 3 and r["index"] == 2

    dr.update_record(repo, "data/raw/d.jsonl", 1, {"i": "edited"})
    dr.delete_record(repo, "data/raw/d.jsonl", 0)

    page = dr.read_records(repo, "data/raw/d.jsonl")
    assert page["total"] == 2
    assert page["records"][0]["data"] == {"i": "edited"}
    assert page["records"][1]["data"] == {"i": 2}
    # a .bak was written on mutation
    assert (repo / "data" / "raw" / "d.jsonl.bak").exists()


def test_validation_and_jail(repo):
    p = repo / "data" / "raw" / "d.jsonl"
    _write(p, [{"i": 0}])
    with pytest.raises(dr.RecordError):
        dr.append_record(repo, "data/raw/d.jsonl", ["not", "an", "object"])
    with pytest.raises(dr.RecordError):
        dr.update_record(repo, "data/raw/d.jsonl", 5, {"i": 1})  # out of range
    with pytest.raises(dr.RecordError):
        dr.append_record(repo, "../escape.jsonl", {"i": 1})       # path jail
    with pytest.raises(dr.RecordError):
        dr.read_records(repo, "data/raw/d.txt")                   # not jsonl
