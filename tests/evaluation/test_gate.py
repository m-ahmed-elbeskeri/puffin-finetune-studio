from __future__ import annotations

import json

from llmops.evaluation.gate import apply_gate

_FULL_METRICS = {
    "task_score": 0.9,
    "task_improvement_over_baseline": 0.1,
    "task_json_validity": 0.99,
    "safety_failures_critical": 0,
    "safety_failures_high": 0,
    "regression_failures": 0,
    "p95_latency_ms": 1000.0,
    "cost_per_1k_requests_usd": 1.5,
}


def test_gate_pass_all_thresholds():
    gates = {
        "min_task_score": 0.85,
        "min_improvement_over_baseline": 0.05,
        "max_safety_failures_critical": 0,
        "max_safety_failures_high": 0,
        "max_regression_failures": 0,
        "min_json_validity": 0.95,
        "max_p95_latency_ms": 2000,
        "max_cost_per_1k_requests_usd": 5.0,
    }
    res = apply_gate(_FULL_METRICS, gates)
    assert res["passed"] is True
    assert res["failures"] == []


def test_gate_fail_low_task_score():
    metrics = {**_FULL_METRICS, "task_score": 0.5}
    res = apply_gate(metrics, {"min_task_score": 0.85})
    assert res["passed"] is False
    assert "min_task_score" in res["failures"]


def test_gate_fail_critical_safety():
    metrics = {**_FULL_METRICS, "safety_failures_critical": 1}
    res = apply_gate(metrics, {"max_safety_failures_critical": 0})
    assert res["passed"] is False


def test_gate_fail_high_latency():
    metrics = {**_FULL_METRICS, "p95_latency_ms": 9999.0}
    res = apply_gate(metrics, {"max_p95_latency_ms": 2000})
    assert res["passed"] is False
    assert "max_p95_latency_ms" in res["failures"]


def test_gate_no_thresholds_pass():
    res = apply_gate({}, {})
    assert res["passed"] is True


def test_gate_cli_writes_report(tmp_path, monkeypatch):
    metrics_file = tmp_path / "metrics.json"
    metrics_file.write_text(json.dumps(_FULL_METRICS))
    cfg_file = tmp_path / "eval.yaml"
    cfg_file.write_text(
        "gates:\n  min_task_score: 0.5\noutput:\n  metrics_path: " + str(metrics_file) + "\n"
    )
    monkeypatch.chdir(tmp_path)
    from llmops.evaluation.gate import main

    rc = main(["--config", str(cfg_file), "--metrics", str(metrics_file)])
    assert rc == 0
    assert (tmp_path / "artifacts" / "eval" / "gate_report.json").exists()
