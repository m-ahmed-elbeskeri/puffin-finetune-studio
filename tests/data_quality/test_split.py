from __future__ import annotations

import json

import pytest

from llmops.common.errors import DataValidationError
from llmops.data.split import _stratified_split, split


def test_split_ratios_must_sum_to_one(tmp_path):
    src = tmp_path / "in.jsonl"
    src.write_text(
        json.dumps({"id": "1", "source": "x", "messages": [{"role": "user", "content": "hi"}]})
        + "\n"
    )
    cfg = {
        "paths": {
            "deduped": str(src),
            "train": str(tmp_path / "tr.jsonl"),
            "eval": str(tmp_path / "ev.jsonl"),
            "test": str(tmp_path / "te.jsonl"),
        },
        "split": {
            "train": 0.5,
            "eval": 0.4,
            "test": 0.4,
            "seed": 0,
            "leakage_threshold": 0.99,
            "leakage_max": 0,
        },
    }
    with pytest.raises(ValueError, match="sum to 1"):
        split(cfg)


def test_stratified_split_deterministic():
    records = [{"id": str(i), "source": "a" if i < 50 else "b"} for i in range(100)]
    parts1 = _stratified_split(records, {"train": 0.7, "eval": 0.15, "test": 0.15}, seed=42)
    parts2 = _stratified_split(records, {"train": 0.7, "eval": 0.15, "test": 0.15}, seed=42)
    assert [r["id"] for r in parts1["train"]] == [r["id"] for r in parts2["train"]]


def test_stratified_split_balanced_per_source():
    records = [{"id": str(i), "source": "a" if i < 50 else "b"} for i in range(100)]
    parts = _stratified_split(records, {"train": 0.6, "eval": 0.2, "test": 0.2}, seed=0)
    sources_in_train = {r["source"] for r in parts["train"]}
    assert sources_in_train == {"a", "b"}


def test_split_full_pipeline(tmp_path):
    src = tmp_path / "in.jsonl"
    with src.open("w", encoding="utf-8") as f:
        for i in range(40):
            f.write(
                json.dumps(
                    {
                        "id": f"r{i}",
                        "source": "alpha" if i % 2 == 0 else "beta",
                        "messages": [
                            {"role": "user", "content": f"unique question {i}"},
                            {"role": "assistant", "content": f"unique answer {i}"},
                        ],
                    }
                )
                + "\n"
            )
    cfg = {
        "paths": {
            "deduped": str(src),
            "train": str(tmp_path / "tr.jsonl"),
            "eval": str(tmp_path / "ev.jsonl"),
            "test": str(tmp_path / "te.jsonl"),
        },
        "split": {
            "train": 0.7,
            "eval": 0.15,
            "test": 0.15,
            "seed": 7,
            "leakage_threshold": 0.99,
            "leakage_max": 0,
        },
    }
    out = split(cfg)
    n_train = sum(1 for _ in out["train"].open())
    n_eval = sum(1 for _ in out["eval"].open())
    n_test = sum(1 for _ in out["test"].open())
    assert n_train + n_eval + n_test == 40
    assert n_train > n_eval
    assert n_train > n_test


def test_split_falls_back_to_interim_when_no_dedupe(tmp_path):
    """Redact/dedupe are optional now, so split must read the raw interim when
    deduped.jsonl and redacted.jsonl were never produced."""
    interim = tmp_path / "interim" / "all.jsonl"
    interim.parent.mkdir()
    with interim.open("w", encoding="utf-8") as f:
        for i in range(30):
            f.write(
                json.dumps(
                    {
                        "id": f"r{i}",
                        "source": "x",
                        "messages": [
                            {"role": "user", "content": f"q{i}"},
                            {"role": "assistant", "content": f"a{i}"},
                        ],
                    }
                )
                + "\n"
            )
    cfg = {
        "paths": {
            # deduped + redacted point at files that do NOT exist
            "deduped": str(tmp_path / "interim" / "deduped.jsonl"),
            "redacted": str(tmp_path / "interim" / "redacted.jsonl"),
            "interim": str(interim),
            "train": str(tmp_path / "tr.jsonl"),
            "eval": str(tmp_path / "ev.jsonl"),
            "test": str(tmp_path / "te.jsonl"),
        },
        "split": {
            "train": 0.7,
            "eval": 0.15,
            "test": 0.15,
            "seed": 1,
            "leakage_threshold": 0.99,
            "leakage_max": 0,
        },
    }
    out = split(cfg)
    total = sum(sum(1 for _ in out[k].open()) for k in ("train", "eval", "test"))
    assert total == 30


def test_split_clear_error_when_nothing_ingested(tmp_path):
    cfg = {
        "paths": {
            "deduped": str(tmp_path / "interim" / "deduped.jsonl"),
            "redacted": str(tmp_path / "interim" / "redacted.jsonl"),
            "interim": str(tmp_path / "interim" / "all.jsonl"),
            "train": str(tmp_path / "tr.jsonl"),
            "eval": str(tmp_path / "ev.jsonl"),
            "test": str(tmp_path / "te.jsonl"),
        },
        "split": {"train": 0.7, "eval": 0.15, "test": 0.15, "seed": 1},
    }
    with pytest.raises(DataValidationError, match="ingest"):
        split(cfg)


def test_leakage_check_blocks_when_train_test_identical(tmp_path):
    src = tmp_path / "in.jsonl"
    with src.open("w", encoding="utf-8") as f:
        for i in range(20):
            content = "totally identical content used to force leakage detection"
            f.write(
                json.dumps(
                    {
                        "id": f"r{i}",
                        "source": "x",
                        "messages": [{"role": "user", "content": content}],
                    }
                )
                + "\n"
            )
    cfg = {
        "paths": {
            "deduped": str(src),
            "train": str(tmp_path / "tr.jsonl"),
            "eval": str(tmp_path / "ev.jsonl"),
            "test": str(tmp_path / "te.jsonl"),
        },
        "split": {
            "train": 0.5,
            "eval": 0.25,
            "test": 0.25,
            "seed": 0,
            "leakage_threshold": 0.5,
            "leakage_max": 0,
        },
    }
    # The leakage check requires datasketch — only assert if it's available.
    try:
        import datasketch  # type: ignore  # noqa: F401
    except ImportError:
        return
    with pytest.raises(DataValidationError, match="leakage"):
        split(cfg)
