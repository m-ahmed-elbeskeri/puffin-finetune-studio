"""End-to-end test of the data pipeline against the example dataset."""
from __future__ import annotations

import shutil
from pathlib import Path


def test_full_data_pipeline(tmp_path, repo_root):
    """Run ingest → validate → redact → dedupe → split → card on the shipped example."""
    work = tmp_path / "data"
    raw = work / "raw"
    raw.mkdir(parents=True)
    shutil.copy(repo_root / "tests" / "fixtures" / "example.jsonl", raw / "example.jsonl")

    cfg = {
        "name": "test",
        "description": "test",
        "contracts_dir": str(repo_root / "data_contracts"),
        "schema_filename": "sft_schema.json",
        "sources": [{"name": "example", "path": str(raw / "example.jsonl")}],
        "paths": {
            "interim":  str(work / "interim/all.jsonl"),
            "redacted": str(work / "interim/redacted.jsonl"),
            "deduped":  str(work / "interim/deduped.jsonl"),
            "train":    str(work / "processed/train.jsonl"),
            "eval":     str(work / "processed/eval.jsonl"),
            "test":     str(work / "processed/test.jsonl"),
        },
        "dataset_card": str(work / "card.md"),
        "forbidden_licenses": [],
        "max_total_chars": 200_000,
        "pii": {"deny_terms": []},
        "dedupe": {"jaccard_threshold": 0.95, "num_perm": 64, "shingle_k": 5},
        "split": {"train": 0.7, "eval": 0.15, "test": 0.15, "seed": 42, "leakage_threshold": 0.95, "leakage_max": 5},
    }

    from llmops.data.build_dataset_card import build_dataset_card
    from llmops.data.dedupe import dedupe
    from llmops.data.ingest import ingest
    from llmops.data.redact_pii import redact
    from llmops.data.split import split
    from llmops.data.validate import validate

    ingest(cfg)
    validate(cfg)
    redact(cfg)
    dedupe(cfg)
    split(cfg)
    card = build_dataset_card(cfg)

    assert Path(cfg["paths"]["train"]).exists()
    assert Path(cfg["paths"]["eval"]).exists()
    assert Path(cfg["paths"]["test"]).exists()
    assert card.exists()
    text = card.read_text(encoding="utf-8")
    assert "Dataset card" in text
    assert "train" in text
