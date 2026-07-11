"""project_status — overall pipeline state, hardware, current model versions."""
from __future__ import annotations

import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from copilot.backend.tools.registry import ToolContext, tool


class _Empty(BaseModel):
    pass


def _has_processed_splits(repo: Path) -> bool:
    return (repo / "data" / "processed" / "train.jsonl").exists()


def _has_raw_data(repo: Path) -> bool:
    raw = repo / "data" / "raw"
    return raw.exists() and any(raw.glob("*.jsonl"))


def _has_adapter(repo: Path) -> bool:
    a = repo / "artifacts" / "adapter"
    return a.exists() and any(a.iterdir())


def _gate(repo: Path) -> bool | None:
    p = repo / "artifacts" / "eval" / "gate_report.json"
    if not p.exists():
        return None
    try:
        import json
        return bool(json.loads(p.read_text(encoding="utf-8")).get("passed"))
    except Exception:  # noqa: BLE001
        return None


def _registry_models(repo: Path) -> list[str]:
    r = repo / "artifacts" / "_registry"
    if not r.exists():
        return []
    return sorted(p.name for p in r.iterdir() if p.is_dir())


def _gpu_summary() -> dict[str, Any]:
    out: dict[str, Any] = {"available": False}
    try:
        r = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=name,memory.total,memory.used,driver_version",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=1.5,
        )
        if r.returncode == 0 and r.stdout.strip():
            parts = [x.strip() for x in r.stdout.splitlines()[0].split(",")]
            name, mem_total, mem_used, drv = parts[:4]
            out.update({
                "available": True,
                "name": name,
                "vram_total_gb": round(int(mem_total) / 1024, 1),
                "vram_used_gb": round(int(mem_used) / 1024, 1),
                "driver": drv,
            })
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        pass
    return out


@tool(
    "project_status",
    description=(
        "Return the overall state of the Puffin project: where the user is in "
        "the data → train → evaluate → deploy → monitor pipeline, hardware "
        "summary, registry contents, and which next action would most help. "
        "ALWAYS call this first when starting a new conversation so you can "
        "ground subsequent suggestions in the actual project state."
    ),
    args_model=_Empty,
)
async def project_status(args: _Empty, ctx: ToolContext) -> dict[str, Any]:
    repo = ctx.repo_root
    has_proc = _has_processed_splits(repo)
    has_raw = _has_raw_data(repo)
    has_adapter = _has_adapter(repo)
    gate = _gate(repo)
    registry = _registry_models(repo)
    metrics_path = repo / "artifacts" / "eval" / "metrics.json"
    has_metrics = metrics_path.exists()
    request_log = repo / "artifacts" / "serving" / "requests.jsonl"

    # If raw data is gone, treat every downstream step as pending — any
    # processed/adapter/eval artifacts left on disk are stale orphans from
    # a previous dataset and should not be reported as "done".
    raw_blocked = not has_raw

    steps = []
    steps.append({
        "key": "data",
        "label": "Data",
        "status": "pending" if raw_blocked
                  else ("done" if has_proc else "current"),
        "sub": "no raw data" if raw_blocked
               else ("splits ready" if has_proc else "pipeline not run"),
    })
    steps.append({
        "key": "train",
        "label": "Train",
        "status": "pending" if (raw_blocked or not has_proc)
                  else ("done" if has_adapter else "current"),
        "sub": "needs data" if raw_blocked
               else ("adapter saved" if has_adapter
                     else ("ready to train" if has_proc else "needs data")),
    })
    if raw_blocked or not has_adapter:
        eval_step = {"status": "pending", "sub": "needs adapter"}
    elif gate is True:
        eval_step = {"status": "done", "sub": "gate PASS"}
    elif gate is False:
        eval_step = {"status": "fail", "sub": "gate FAIL"}
    elif has_metrics:
        eval_step = {"status": "current", "sub": "gate not run"}
    else:
        eval_step = {"status": "current", "sub": "ready to eval"}
    steps.append({"key": "evaluate", "label": "Evaluate", **eval_step})
    if raw_blocked:
        deploy_step = {"status": "pending", "sub": "needs data"}
    elif registry:
        deploy_step = {"status": "done", "sub": f"{len(registry)} in registry"}
    elif gate:
        deploy_step = {"status": "current", "sub": "ready to push"}
    else:
        deploy_step = {"status": "pending", "sub": "needs gate PASS"}
    steps.append({"key": "deploy", "label": "Deploy", **deploy_step})
    if raw_blocked or not registry:
        mon = {"status": "pending", "sub": "needs deploy"}
    elif request_log.exists():
        mon = {"status": "done", "sub": "traffic logged"}
    else:
        mon = {"status": "current", "sub": "no traffic yet"}
    steps.append({"key": "monitor", "label": "Monitor", **mon})

    # Next-action recommendation — single string the LLM can quote back.
    if not has_raw:
        next_action = "Drop a JSONL of training examples into data/raw/."
    elif not has_proc:
        next_action = "Run the data pipeline (data_pipeline_run tool)."
    elif not has_adapter:
        next_action = "Start a smoke train (train_start tool, smoke=true)."
    elif gate is None:
        next_action = "Run evaluation + gate (eval_run + gate_apply tools)."
    elif gate is False:
        next_action = "Gate failed — inspect failures and retrain or relax thresholds."
    elif not registry:
        next_action = "Push the adapter to the registry (deploy_push tool)."
    else:
        next_action = "Chat with the deployed model (serve_chat tool)."

    return {
        "kind": "project_status",
        "repo_root": str(repo),
        "steps": steps,
        "next_action": next_action,
        "registry_models": registry,
        "hardware": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "cpu_count": __import__("os").cpu_count(),
            "ram_gb": round(_psutil_ram_gb(), 1),
            "disk_free_gb": round(
                shutil.disk_usage(repo).free / 1024**3, 1),
            "gpu": _gpu_summary(),
        },
    }


def _psutil_ram_gb() -> float:
    try:
        import psutil
        return psutil.virtual_memory().total / 1024**3
    except Exception:  # noqa: BLE001
        return 0.0


