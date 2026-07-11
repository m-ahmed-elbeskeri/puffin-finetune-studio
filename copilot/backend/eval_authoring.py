"""Edit the promotion-gate thresholds in configs/eval.yaml.

Uses a ruamel round-trip load/dump so the rest of the file (comments, ordering,
other blocks) survives untouched. Only known gate keys with numeric values are
accepted, so the studio can't write junk into the gate.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

KNOWN_GATES: dict[str, str] = {
    "min_task_score": "min",
    "min_improvement_over_baseline": "min",
    "max_safety_failures_critical": "max",
    "max_safety_failures_high": "max",
    "max_regression_failures": "max",
    "min_json_validity": "min",
    "max_p95_latency_ms": "max",
    "max_cost_per_1k_requests_usd": "max",
}


class EvalAuthoringError(ValueError):
    """Bad gate key or value; maps to HTTP 400."""


def _eval_path(repo_root: Path) -> Path:
    return Path(repo_root) / "configs" / "eval.yaml"


def read_gates(repo_root: Path) -> dict[str, float]:
    import yaml
    p = _eval_path(repo_root)
    if not p.exists():
        return {}
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise EvalAuthoringError(f"configs/eval.yaml is not valid YAML: {exc}") from exc
    gates = data.get("gates") or {}
    return {k: v for k, v in gates.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)}


def update_gates(repo_root: Path, gates: dict[str, Any]) -> dict[str, float]:
    """Merge validated gate values into configs/eval.yaml, preserving the rest."""
    p = _eval_path(repo_root)
    if not p.exists():
        raise EvalAuthoringError("configs/eval.yaml not found")

    clean: dict[str, float] = {}
    for key, val in (gates or {}).items():
        if key not in KNOWN_GATES:
            raise EvalAuthoringError(f"unknown gate: {key!r}")
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise EvalAuthoringError(f"gate {key!r} must be a number")
        if val < 0:
            raise EvalAuthoringError(f"gate {key!r} must be >= 0")
        clean[key] = val
    if not clean:
        raise EvalAuthoringError("no valid gate values provided")

    from ruamel.yaml import YAML
    yaml_rt = YAML()
    yaml_rt.preserve_quotes = True
    with p.open("r", encoding="utf-8") as fh:
        doc = yaml_rt.load(fh)
    if doc is None:
        doc = {}
    if doc.get("gates") is None:
        doc["gates"] = {}
    for key, val in clean.items():
        # Keep counts as ints, scores/latency/cost as given.
        doc["gates"][key] = int(val) if float(val).is_integer() and "failures" in key else val

    # Safety net: keep a .bak of the previous file.
    try:
        p.with_suffix(".yaml.bak").write_text(
            p.read_text(encoding="utf-8"), encoding="utf-8")
    except OSError:
        pass
    with p.open("w", encoding="utf-8") as fh:
        yaml_rt.dump(doc, fh)
    return read_gates(repo_root)
