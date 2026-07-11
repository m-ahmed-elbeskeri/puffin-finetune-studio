"""Evaluation tools — run evals + apply gate."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from copilot.backend.tools.registry import ToolContext, ToolError, tool


VALID_MODULES = {"task_eval", "safety_eval", "regression_eval", "latency_eval"}


class EvalRunArgs(BaseModel):
    modules: list[str] = Field(
        default_factory=lambda: list(VALID_MODULES),
        description="Subset of {task_eval, safety_eval, regression_eval, latency_eval}.",
    )
    backend: str = Field(
        default="transformers",
        description="'transformers' runs real generation against eval.model_id "
                    "+ adapter (the default).",
    )
    config: str = Field(default="configs/eval.yaml")


@tool(
    "eval_run",
    description=(
        "Run one or more evaluation modules against the served/adapter model. "
        "Writes artifacts/eval/metrics.json."
    ),
    args_model=EvalRunArgs,
    dangerous=True,
)
async def eval_run(args: EvalRunArgs, ctx: ToolContext) -> dict[str, Any]:
    cfg = (ctx.repo_root / args.config).resolve()
    if not cfg.exists():
        raise ToolError(f"config not found: {args.config}")
    bad = [m for m in args.modules if m not in VALID_MODULES]
    if bad:
        raise ToolError(f"unknown eval modules: {bad}")

    import os
    env = os.environ.copy()
    env["PUFFIN_EVAL_BACKEND"] = args.backend

    results = []
    for module in args.modules:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", f"llmops.evaluation.{module}",
            "--config", str(cfg),
            cwd=str(ctx.repo_root), env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await proc.communicate()
        text = out.decode("utf-8", errors="replace")
        results.append({
            "module": module,
            "exit_code": proc.returncode,
            "ok": proc.returncode == 0,
            "stdout_tail": "\n".join(text.splitlines()[-15:]),
        })
        if proc.returncode != 0:
            break

    metrics_path = ctx.repo_root / "artifacts" / "eval" / "metrics.json"
    metrics = {}
    if metrics_path.exists():
        try:
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            metrics = {}

    return {
        "kind": "eval_result",
        "modules": results,
        "all_ok": all(r["ok"] for r in results),
        "metrics_summary": {
            k: metrics.get(k) for k in (
                "task_score", "safety_failures_critical", "safety_failures_high",
                "regression_failures", "p50_latency_ms", "p95_latency_ms",
                "p99_latency_ms", "cost_per_1k_requests_usd",
            )
        },
    }


class _Empty(BaseModel):
    pass


@tool(
    "gate_apply",
    description=(
        "Apply the promotion gate (thresholds in configs/eval.yaml) to the "
        "latest metrics.json. Returns PASS or FAIL with per-criterion verdicts. "
        "Renders as a gate card."
    ),
    args_model=_Empty,
    dangerous=True,
)
async def gate_apply(args: _Empty, ctx: ToolContext) -> dict[str, Any]:
    cfg = ctx.repo_root / "configs" / "eval.yaml"
    metrics = ctx.repo_root / "artifacts" / "eval" / "metrics.json"
    if not metrics.exists():
        raise ToolError("artifacts/eval/metrics.json does not exist — run eval_run first.")

    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "llmops.evaluation.gate",
        "--config", str(cfg),
        "--metrics", str(metrics),
        cwd=str(ctx.repo_root),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    text = out.decode("utf-8", errors="replace")

    report_path = ctx.repo_root / "artifacts" / "eval" / "gate_report.json"
    report = {}
    if report_path.exists():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            report = {}

    return {
        "kind": "gate_result",
        "passed": bool(report.get("passed", False)),
        "failures": report.get("failures", []),
        "passes": report.get("passes", []),
        "criteria": report.get("criteria", []),
        "exit_code": proc.returncode,
        "stdout_tail": "\n".join(text.splitlines()[-10:]),
    }


@tool(
    "eval_get_metrics",
    description=(
        "Return the latest eval metrics.json (task score, safety failures, "
        "latency percentiles, cost, etc.). Renders as a metrics summary card."
    ),
    args_model=_Empty,
)
async def eval_get_metrics(args: _Empty, ctx: ToolContext) -> dict[str, Any]:
    p = ctx.repo_root / "artifacts" / "eval" / "metrics.json"
    if not p.exists():
        return {"kind": "eval_metrics", "present": False}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ToolError(f"metrics.json is corrupt: {exc}") from exc
    return {"kind": "eval_metrics", "present": True, "metrics": data}
