from __future__ import annotations

import json

import pytest

from llmops.common.errors import DataValidationError
from llmops.data.validate import validate


def _write(tmp_path, records):
    p = tmp_path / "interim.jsonl"
    with p.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r))
            f.write("\n")
    return p


def test_validate_passes_clean_data(tmp_path, repo_root):
    interim = _write(
        tmp_path,
        [
            {
                "id": "1",
                "source": "test",
                "messages": [{"role": "user", "content": "hi"}],
                "quality_score": 0.9,
                "license": "internal",
                "contains_pii": False,
            }
        ],
    )
    cfg = {
        "paths": {"interim": str(interim)},
        "contracts_dir": str(repo_root / "data_contracts"),
        "schema_filename": "sft_schema.json",
        "forbidden_licenses": [],
    }
    res = validate(cfg)
    assert res == {"total": 1, "pii_marked": 0, "errors": 0}


def test_validate_fails_on_unknown_role(tmp_path, repo_root):
    interim = _write(
        tmp_path,
        [{"id": "1", "source": "test", "messages": [{"role": "robot", "content": "hi"}]}],
    )
    cfg = {
        "paths": {"interim": str(interim)},
        "contracts_dir": str(repo_root / "data_contracts"),
        "schema_filename": "sft_schema.json",
    }
    with pytest.raises(DataValidationError):
        validate(cfg)


def test_validate_blocks_forbidden_license(tmp_path, repo_root):
    interim = _write(
        tmp_path,
        [
            {
                "id": "1",
                "source": "test",
                "messages": [{"role": "user", "content": "hi"}],
                "license": "proprietary-noredistribute",
            }
        ],
    )
    cfg = {
        "paths": {"interim": str(interim)},
        "contracts_dir": str(repo_root / "data_contracts"),
        "schema_filename": "sft_schema.json",
        "forbidden_licenses": ["proprietary-noredistribute"],
    }
    with pytest.raises(DataValidationError, match="forbidden license"):
        validate(cfg)


def test_validate_blocks_too_long(tmp_path, repo_root):
    interim = _write(
        tmp_path,
        [
            {
                "id": "1",
                "source": "test",
                "messages": [{"role": "user", "content": "x" * 2000}],
            }
        ],
    )
    cfg = {
        "paths": {"interim": str(interim)},
        "contracts_dir": str(repo_root / "data_contracts"),
        "schema_filename": "sft_schema.json",
        "max_total_chars": 100,
    }
    with pytest.raises(DataValidationError, match="total chars"):
        validate(cfg)
