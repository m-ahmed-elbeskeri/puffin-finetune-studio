"""Monitoring tools — request log tail, quality/drift reports."""
from __future__ import annotations

import json
from collections import Counter
from typing import Any

from pydantic import BaseModel, Field

from copilot.backend.tools.registry import ToolContext, tool


def _read_jsonl_tail(path, *, n: int) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        lines = fh.readlines()
    for line in lines[-n:]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _read_jsonl_all(path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


class RequestLogArgs(BaseModel):
    n: int = Field(default=25, ge=1, le=500)


@tool(
    "monitor_request_log",
    description=(
        "Tail the serving request log (artifacts/serving/requests.jsonl). "
        "Returns recent requests + summary distributions "
        "(latency, output length, model versions hit)."
    ),
    args_model=RequestLogArgs,
)
async def monitor_request_log(args: RequestLogArgs, ctx: ToolContext) -> dict[str, Any]:
    path = ctx.repo_root / "artifacts" / "serving" / "requests.jsonl"
    all_rows = _read_jsonl_all(path)
    if not all_rows:
        return {"kind": "request_log", "present": False, "total": 0}
    latest = all_rows[-args.n:]
    latencies = [float(r.get("latency_ms", 0)) for r in all_rows
                 if "latency_ms" in r]
    out_chars = [int(r.get("output_chars", 0)) for r in all_rows
                 if isinstance(r.get("output_chars", 0), (int, float))]
    by_model = Counter(r.get("model_version", "?") for r in all_rows)
    avg = sum(latencies) / len(latencies) if latencies else 0
    return {
        "kind": "request_log",
        "present": True,
        "total": len(all_rows),
        "recent": latest,
        "summary": {
            "avg_latency_ms": round(avg, 2),
            "total_output_chars": sum(out_chars),
            "by_model_version": dict(by_model),
        },
    }


class _Empty(BaseModel):
    pass


@tool(
    "monitor_quality",
    description=(
        "Read the latest quality monitor result (artifacts/monitoring/quality.json) — "
        "refusal rate, JSON validity rate, optional LLM-judge score."
    ),
    args_model=_Empty,
)
async def monitor_quality(args: _Empty, ctx: ToolContext) -> dict[str, Any]:
    p = ctx.repo_root / "artifacts" / "monitoring" / "quality.json"
    if not p.exists():
        return {"kind": "quality_report", "present": False}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"kind": "quality_report", "present": False,
                "error": "quality.json is invalid"}
    return {"kind": "quality_report", "present": True, "report": data}


@tool(
    "monitor_drift",
    description=(
        "Read the latest drift monitor result (artifacts/monitoring/drift.json) — "
        "prod-vs-train prompt length KS statistic + optional embedding drift."
    ),
    args_model=_Empty,
)
async def monitor_drift(args: _Empty, ctx: ToolContext) -> dict[str, Any]:
    p = ctx.repo_root / "artifacts" / "monitoring" / "drift.json"
    if not p.exists():
        return {"kind": "drift_report", "present": False}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"kind": "drift_report", "present": False,
                "error": "drift.json is invalid"}
    return {"kind": "drift_report", "present": True, "report": data}
