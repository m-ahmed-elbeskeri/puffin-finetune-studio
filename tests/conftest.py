"""Pytest fixtures."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Ensure src/ is importable when running pytest from the repo root.
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture(autouse=True)
def _isolated_artifact_root(tmp_path, monkeypatch):
    """Per-test sandbox for any code that uses PUFFIN_ARTIFACT_ROOT."""
    sandbox = tmp_path / "artifacts"
    sandbox.mkdir()
    monkeypatch.setenv("PUFFIN_ARTIFACT_ROOT", str(sandbox))
    monkeypatch.setenv("PUFFIN_TRACKING_BACKEND", "none")
    monkeypatch.setenv("PUFFIN_LOG_FORMAT", "text")
    yield sandbox


@pytest.fixture
def sample_sft_record() -> dict:
    return {
        "id": "ex-001",
        "source": "test",
        "messages": [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello."},
            {"role": "assistant", "content": "Hi!"},
        ],
        "quality_score": 0.9,
        "license": "internal",
        "contains_pii": False,
    }


@pytest.fixture
def sample_jsonl_path(tmp_path, sample_sft_record) -> Path:
    p = tmp_path / "sample.jsonl"
    with p.open("w", encoding="utf-8") as f:
        for i in range(5):
            rec = dict(sample_sft_record)
            rec["id"] = f"ex-{i:03d}"
            f.write(json.dumps(rec))
            f.write("\n")
    return p


@pytest.fixture
def repo_root() -> Path:
    return ROOT
