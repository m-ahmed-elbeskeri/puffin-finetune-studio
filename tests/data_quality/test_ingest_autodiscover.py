"""Zero-config ingest: empty `sources:` auto-discovers data/raw/*.jsonl."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from llmops.data.ingest import ingest


def _cfg(tmp_path: Path) -> dict:
    return {
        "sources": [],
        "paths": {"interim": str(tmp_path / "interim" / "all.jsonl")},
    }


def _write_jsonl(p: Path, rows: list[dict]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_empty_sources_discovers_raw_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_jsonl(tmp_path / "data" / "raw" / "tickets.jsonl", [
        {"messages": [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]},
    ])
    out = ingest(_cfg(tmp_path))
    rows = [json.loads(line) for line in
            Path(out).read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    # Source name comes from the file stem.
    assert rows[0]["source"] == "tickets"


def test_empty_sources_and_empty_raw_dir_raises(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "raw").mkdir(parents=True)
    with pytest.raises(ValueError, match="no data sources"):
        ingest(_cfg(tmp_path))


def test_explicit_sources_take_precedence(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # A decoy in data/raw that must NOT be ingested.
    _write_jsonl(tmp_path / "data" / "raw" / "decoy.jsonl", [
        {"messages": [{"role": "user", "content": "decoy"},
                      {"role": "assistant", "content": "x"}]},
    ])
    _write_jsonl(tmp_path / "custom" / "picked.jsonl", [
        {"messages": [{"role": "user", "content": "real"},
                      {"role": "assistant", "content": "y"}]},
    ])
    cfg = _cfg(tmp_path)
    cfg["sources"] = [{"name": "picked", "path": str(tmp_path / "custom" / "picked.jsonl")}]
    out = ingest(cfg)
    rows = [json.loads(line) for line in
            Path(out).read_text(encoding="utf-8").splitlines()]
    assert [r["source"] for r in rows] == ["picked"]
