from __future__ import annotations

import json

from llmops.data.dedupe import _select_keepers_exact, dedupe


def _records():
    return [
        {"id": "a", "messages": [{"role": "user", "content": "Hello world"}], "quality_score": 0.5},
        {"id": "b", "messages": [{"role": "user", "content": "Hello world"}], "quality_score": 0.9},
        {"id": "c", "messages": [{"role": "user", "content": "Totally different question"}], "quality_score": 0.7},
    ]


def test_exact_dedup_keeps_higher_quality():
    keepers = _select_keepers_exact(_records())
    kept = sorted(keepers)
    assert len(kept) == 2
    # b (quality 0.9) should beat a (0.5); c is unique.
    record_ids = [_records()[i]["id"] for i in kept]
    assert "b" in record_ids
    assert "c" in record_ids
    assert "a" not in record_ids


def test_dedupe_pipeline_writes_output(tmp_path):
    src = tmp_path / "in.jsonl"
    out = tmp_path / "out.jsonl"
    with src.open("w", encoding="utf-8") as f:
        for r in _records():
            f.write(json.dumps(r))
            f.write("\n")
    cfg = {
        "paths": {"redacted": str(src), "deduped": str(out)},
        "dedupe": {"jaccard_threshold": 0.95, "num_perm": 64, "shingle_k": 3},
    }
    dedupe(cfg)
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert 2 <= len(lines) <= 3
