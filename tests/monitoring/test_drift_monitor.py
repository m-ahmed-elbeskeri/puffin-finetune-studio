from __future__ import annotations

import json

from llmops.monitoring.drift_monitor import _ks_two_sample, run


def test_ks_identical_distributions():
    a = list(range(100))
    b = list(range(100))
    assert _ks_two_sample(a, b) == 0.0


def test_ks_disjoint_distributions():
    a = [0, 1, 2, 3]
    b = [100, 101, 102, 103]
    assert _ks_two_sample(a, b) > 0.5


def test_ks_empty_inputs():
    assert _ks_two_sample([], [1, 2]) == 0.0
    assert _ks_two_sample([1, 2], []) == 0.0


def test_drift_monitor_with_no_files(tmp_path):
    out = tmp_path / "drift.json"
    summary = run(
        prod_path=str(tmp_path / "missing-prod.jsonl"),
        train_path=str(tmp_path / "missing-train.jsonl"),
        output_path=str(out),
    )
    assert summary["prod_prompts"] == 0
    assert summary["train_prompts"] == 0
    assert json.loads(out.read_text(encoding="utf-8"))["drift_warning"] is False


def test_drift_monitor_with_data(tmp_path):
    prod = tmp_path / "prod.jsonl"
    train = tmp_path / "train.jsonl"
    with prod.open("w", encoding="utf-8") as f:
        for _ in range(20):
            f.write(json.dumps({"input_messages": [{"role": "user", "content": "x" * 50}]}) + "\n")
    with train.open("w", encoding="utf-8") as f:
        for _ in range(20):
            f.write(json.dumps({"messages": [{"role": "user", "content": "x" * 50}]}) + "\n")

    summary = run(
        prod_path=str(prod),
        train_path=str(train),
        output_path=str(tmp_path / "drift.json"),
    )
    assert summary["prod_prompts"] == 20
    assert summary["train_prompts"] == 20
    assert summary["length_ks_statistic"] == 0.0
