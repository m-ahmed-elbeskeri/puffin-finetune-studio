from __future__ import annotations

import json

from llmops.monitoring.quality_monitor import run


def test_quality_monitor_no_log(tmp_path):
    summary = run(
        requests_path=str(tmp_path / "missing.jsonl"),
        output_path=str(tmp_path / "quality.json"),
    )
    assert summary["sampled"] == 0


def test_quality_monitor_basic(tmp_path):
    requests = tmp_path / "requests.jsonl"
    records = []
    for i in range(10):
        records.append(
            {
                "request_id": f"r{i}",
                "output_text": "I'm sorry, I can't help with that." if i < 3 else '{"ok": true}',
                "model_version": "v1",
            }
        )
    with requests.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r))
            f.write("\n")

    summary = run(
        requests_path=str(requests),
        output_path=str(tmp_path / "q.json"),
        sample_size=10,
    )
    assert summary["sampled"] == 10
    assert 0.2 <= summary["refusal_rate"] <= 0.4
    assert 0.6 <= summary["json_validity_rate"] <= 0.8
    assert summary["by_model_version"] == {"v1": 10}
