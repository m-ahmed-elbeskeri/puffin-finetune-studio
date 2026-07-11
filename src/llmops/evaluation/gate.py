"""Promotion gate: read aggregated metrics.json, apply thresholds, exit non-zero on fail.

Reads thresholds from `configs/eval.yaml::gates`. Each check produces a single
line in the report; the process exits 1 if any check fails.

Returns a dict {"passed": bool, "failures": [str], "report": [str]} for
programmatic callers; the CLI prints the report and uses sys.exit.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from llmops.common.config import load_yaml
from llmops.common.errors import GateError
from llmops.common.logging import get_logger
from llmops.evaluation.metrics_store import load_metrics

log = get_logger(__name__)


def _check_min(label: str, actual: float, threshold: float) -> tuple[bool, str]:
    ok = actual >= threshold
    return ok, f"  [{'OK' if ok else 'FAIL'}] {label}: {actual:.4f} (min {threshold})"


def _check_max(label: str, actual: float, threshold: float) -> tuple[bool, str]:
    ok = actual <= threshold
    return ok, f"  [{'OK' if ok else 'FAIL'}] {label}: {actual:.4f} (max {threshold})"


def _check_int_max(label: str, actual: int, threshold: int) -> tuple[bool, str]:
    ok = actual <= threshold
    return ok, f"  [{'OK' if ok else 'FAIL'}] {label}: {actual} (max {threshold})"


def _check_bool(label: str, actual: bool, expected: bool) -> tuple[bool, str]:
    ok = actual == expected
    return ok, f"  [{'OK' if ok else 'FAIL'}] {label}: {actual} (expected {expected})"


def apply_gate(metrics: dict[str, Any], gates: dict[str, Any]) -> dict[str, Any]:
    """Apply each configured gate. Returns a summary dict (does not raise)."""
    checks: list[tuple[str, bool, str]] = []

    if "min_task_score" in gates:
        ok, msg = _check_min(
            "task_score", float(metrics.get("task_score", 0.0)), float(gates["min_task_score"])
        )
        checks.append(("min_task_score", ok, msg))

    if "min_improvement_over_baseline" in gates:
        improvement = float(metrics.get("task_improvement_over_baseline", 0.0))
        ok, msg = _check_min(
            "task_improvement_over_baseline",
            improvement,
            float(gates["min_improvement_over_baseline"]),
        )
        checks.append(("min_improvement_over_baseline", ok, msg))

    if "max_safety_failures_critical" in gates:
        ok, msg = _check_int_max(
            "safety_failures_critical",
            int(metrics.get("safety_failures_critical", 0)),
            int(gates["max_safety_failures_critical"]),
        )
        checks.append(("max_safety_failures_critical", ok, msg))

    if "max_safety_failures_high" in gates:
        ok, msg = _check_int_max(
            "safety_failures_high",
            int(metrics.get("safety_failures_high", 0)),
            int(gates["max_safety_failures_high"]),
        )
        checks.append(("max_safety_failures_high", ok, msg))

    if "max_regression_failures" in gates:
        ok, msg = _check_int_max(
            "regression_failures",
            int(metrics.get("regression_failures", 0)),
            int(gates["max_regression_failures"]),
        )
        checks.append(("max_regression_failures", ok, msg))

    if "min_json_validity" in gates:
        ok, msg = _check_min(
            "task_json_validity",
            float(metrics.get("task_json_validity", 0.0)),
            float(gates["min_json_validity"]),
        )
        checks.append(("min_json_validity", ok, msg))

    if "max_p95_latency_ms" in gates:
        ok, msg = _check_max(
            "p95_latency_ms",
            float(metrics.get("p95_latency_ms", 0.0)),
            float(gates["max_p95_latency_ms"]),
        )
        checks.append(("max_p95_latency_ms", ok, msg))

    if "max_cost_per_1k_requests_usd" in gates:
        ok, msg = _check_max(
            "cost_per_1k_requests_usd",
            float(metrics.get("cost_per_1k_requests_usd", 0.0)),
            float(gates["max_cost_per_1k_requests_usd"]),
        )
        checks.append(("max_cost_per_1k_requests_usd", ok, msg))

    if "require_eval_set_no_leakage" in gates:
        ok, msg = _check_bool(
            "eval_set_leakage",
            bool(metrics.get("eval_set_leakage", False)),
            False,
        )
        checks.append(("require_eval_set_no_leakage", ok, msg))

    failures = [name for name, ok, _ in checks if not ok]
    report = [
        "Promotion gate report",
        "=====================",
        *[msg for _, _, msg in checks],
        "",
        f"Result: {'PASS' if not failures else 'FAIL'}",
    ]
    return {"passed": not failures, "failures": failures, "report": "\n".join(report)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply the promotion gate.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--metrics", default=None)
    args = parser.parse_args(argv)

    cfg = load_yaml(args.config)
    gates = cfg.get("gates", {})
    metrics_file = Path(
        args.metrics or cfg.get("output", {}).get("metrics_path", "artifacts/eval/metrics.json")
    )
    if not metrics_file.exists():
        raise GateError(f"metrics file not found: {metrics_file}")

    metrics = load_metrics(metrics_file)
    result = apply_gate(metrics, gates)

    print(result["report"])
    Path("artifacts/eval/gate_report.json").parent.mkdir(parents=True, exist_ok=True)
    Path("artifacts/eval/gate_report.json").write_text(
        json.dumps(
            {"passed": result["passed"], "failures": result["failures"]},
            indent=2,
        ),
        encoding="utf-8",
    )

    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
