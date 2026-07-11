"""End-to-end eval suite using the echo backend and shipped eval sets."""
from __future__ import annotations

import json
from pathlib import Path

import yaml


def test_full_eval_suite_with_echo(tmp_path, repo_root, monkeypatch):
    """Run every eval module against the shipped golden/safety/regression/latency sets."""
    monkeypatch.chdir(tmp_path)

    # Materialize a copy of the eval config that points at the shipped JSONL files.
    cfg_src = yaml.safe_load((repo_root / "configs" / "eval.yaml").read_text(encoding="utf-8"))
    cfg_src["eval"]["backend"] = "echo"
    cfg_src["datasets"] = {
        k: str(repo_root / "eval_sets" / Path(v).name) for k, v in cfg_src["datasets"].items()
    }
    cfg_src["output"] = {"metrics_path": str(tmp_path / "metrics.json")}
    cfg_path = tmp_path / "eval.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg_src), encoding="utf-8")

    from llmops.common.config import load_yaml
    from llmops.evaluation.gate import apply_gate
    from llmops.evaluation.latency_eval import run_latency_eval
    from llmops.evaluation.regression_eval import run_regression_eval
    from llmops.evaluation.safety_eval import run_safety_eval
    from llmops.evaluation.task_eval import run_task_eval

    cfg = load_yaml(cfg_path)
    run_task_eval(cfg)
    run_safety_eval(cfg)
    run_regression_eval(cfg)
    run_latency_eval(cfg)

    metrics = json.loads(Path(cfg_src["output"]["metrics_path"]).read_text(encoding="utf-8"))
    for k in (
        "task_score",
        "task_json_validity",
        "safety_failures_critical",
        "regression_failures",
        "p95_latency_ms",
        "cost_per_1k_requests_usd",
    ):
        assert k in metrics, f"missing metric {k}"

    # The shipped echo rules are tuned to pass the gate.
    res = apply_gate(metrics, cfg["gates"])
    assert res["passed"] is True, f"gate failed: {res['failures']}\n{res['report']}"
