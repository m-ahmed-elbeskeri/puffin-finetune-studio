"""Training tools — start / status / history / cancel.

Live state and history are read from the sidecar JSON files written by
`llmops.training._metrics_callback.TrainingMetricsCallback`:
  - training_state.json   (rewritten every step)
  - training_metrics.jsonl (appended every logging_steps)
  - training_summary.json (written once at end)
"""
from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from copilot.backend.tools.registry import ToolContext, ToolError, tool


# ---------------------------------------------------------------------------
# Shared helpers (mirror copilot/frontend's TrainingRun)
# ---------------------------------------------------------------------------
def _safe_json(p: Path) -> dict[str, Any]:
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")) or {}
    except (json.JSONDecodeError, OSError):
        return {}


# Packages the training entrypoints import at module load. If any are missing,
# the subprocess dies before writing a single line of run state — which looks
# like "training vanished." We preflight them so the user gets a clear message.
_TRAIN_DEPS = ("trl", "peft", "accelerate")


def _missing_training_deps() -> list[str]:
    import importlib.util
    return [m for m in _TRAIN_DEPS if importlib.util.find_spec(m) is None]


def _pid_alive(pid: Any) -> bool:
    """True if the process is still running. Used to flip a run whose process
    died (e.g. an import crash) from 'running' to 'failed'."""
    if not pid:
        return False
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    try:
        import psutil
        return psutil.pid_exists(pid)
    except ImportError:
        pass
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def read_training_log(repo_root: Path, adapter_dir: str, *, tail: int = 300) -> dict[str, Any]:
    """Return the tail of a run's training log so the UI can show why a run
    failed. Finds the log via the durable .log_path pointer, falling back to
    the newest log file for the method."""
    repo = Path(repo_root)
    d = (repo / adapter_dir).resolve()
    if not str(d).startswith(str(repo.resolve())):
        raise ToolError("adapter_dir escapes repo root")
    log_file: Path | None = None
    ptr = d / ".log_path"
    if ptr.exists():
        candidate = (repo / ptr.read_text(encoding="utf-8").strip()).resolve()
        if candidate.exists() and str(candidate).startswith(str(repo.resolve())):
            log_file = candidate
    if log_file is None:
        # Fallback: newest log matching the run's method.
        state = _safe_json(d / "training_state.json")
        summary = _safe_json(d / "training_summary.json")
        method = state.get("method") or summary.get("method") or ""
        logs_dir = repo / "artifacts" / "copilot" / "training-logs"
        if logs_dir.exists():
            matches = sorted(
                logs_dir.glob(f"{method}_*.log") if method else logs_dir.glob("*.log"),
                key=lambda p: p.stat().st_mtime, reverse=True)
            if matches:
                log_file = matches[0]
    if log_file is None or not log_file.exists():
        return {"kind": "training_log", "adapter_dir": adapter_dir,
                "present": False, "lines": [],
                "message": "No log file found for this run yet."}
    try:
        text = log_file.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ToolError(f"could not read log: {exc}") from exc
    lines = text.splitlines()
    tail = max(1, min(2000, tail))
    return {
        "kind": "training_log",
        "adapter_dir": adapter_dir,
        "present": True,
        "log_path": str(log_file.relative_to(repo)).replace("\\", "/"),
        "total_lines": len(lines),
        "lines": lines[-tail:],
    }


def read_run_config(repo_root: Path, adapter_dir: str) -> dict[str, Any]:
    """Return the exact config snapshot a run used plus its reproducibility
    metadata (data fingerprint, launch command). Answers "what settings and
    data produced this adapter?" from the run dir alone."""
    repo = Path(repo_root)
    d = (repo / adapter_dir).resolve()
    cfg = d / "run_config.yaml"
    meta_path = d / "run_meta.json"
    meta: dict[str, Any] = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            meta = {}
    if not cfg.exists():
        return {"kind": "run_config", "adapter_dir": adapter_dir,
                "present": False, "meta": meta,
                "message": "No config snapshot for this run (started before "
                           "snapshots, or an older run)."}
    try:
        yaml_text = cfg.read_text(encoding="utf-8")
    except OSError as exc:
        raise ToolError(f"could not read run config: {exc}") from exc
    return {
        "kind": "run_config",
        "adapter_dir": adapter_dir,
        "present": True,
        "config_path": str(cfg.relative_to(repo)).replace("\\", "/"),
        "yaml": yaml_text,
        "meta": meta,
    }


def _derive_stage(status: str, current_step: Any, total_steps: Any) -> str:
    """Human-readable phase for the live card."""
    if status == "completed":
        return "completed"
    if status == "failed":
        return "failed"
    if status == "stalled":
        return "stalled (no update in a while)"
    if status == "starting" or not current_step:
        return "loading model and data"
    if total_steps:
        return f"training: step {current_step} of {total_steps}"
    return "training"


def _candidate_adapter_dirs(repo: Path) -> list[Path]:
    root = repo / "artifacts"
    if not root.exists():
        return []
    out: list[Path] = []
    for p in root.iterdir():
        if not p.is_dir() or p.name.startswith("_"):
            continue
        if (
            (p / "training_summary.json").exists()
            or (p / "training_state.json").exists()
            or (p / "lineage.json").exists()
        ):
            out.append(p)
    return out


def _read_metrics_rows(adapter_dir: Path, *, last_n: int | None = None) -> list[dict]:
    p = adapter_dir / "training_metrics.jsonl"
    if not p.exists():
        return []
    rows: list[dict] = []
    with p.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows[-last_n:] if last_n else rows


def _serialise_run(adapter_dir: Path, *, repo: Path,
                   include_metrics: bool = False) -> dict[str, Any]:
    summary = _safe_json(adapter_dir / "training_summary.json")
    state = _safe_json(adapter_dir / "training_state.json")
    status = summary.get("status") or state.get("status") or "unknown"
    now = datetime.now(timezone.utc)
    pid = state.get("pid")
    error = summary.get("error") or state.get("error")
    # If a run claims to be active but its process is gone (and it hasn't
    # updated recently), it died — commonly a missing-dependency import crash
    # before the first metric was written. The staleness guard avoids a false
    # positive in the split second between launch and the first heartbeat.
    if status in ("running", "starting") and not summary:
        last = state.get("last_update_ts")
        age: float | None = None
        if last:
            try:
                age = (now - datetime.fromisoformat(last)).total_seconds()
            except (TypeError, ValueError):
                age = None
        dead = bool(pid) and not _pid_alive(pid)
        if dead and (age is None or age > 15):
            status = "failed"
            if not error:
                error = ("The training process exited before finishing. "
                         "Check the training log; if it crashed on import, "
                         "install the training extras: pip install -e \".[train]\".")
        elif age is not None and age > 120:
            status = "stalled"

    # Live elapsed: the summary only has duration_s once finished, so compute
    # it from start_ts while a run is still going.
    start_ts = summary.get("start_ts") or state.get("start_ts") or ""
    elapsed_s = summary.get("duration_s")
    if elapsed_s is None and start_ts:
        try:
            elapsed_s = round((now - datetime.fromisoformat(start_ts)).total_seconds(), 1)
        except (TypeError, ValueError):
            elapsed_s = None

    out: dict[str, Any] = {
        "adapter_dir": str(adapter_dir.relative_to(repo)),
        "status": status,
        "method": summary.get("method") or state.get("method") or "?",
        "run_name": summary.get("run_name") or state.get("run_name") or adapter_dir.name,
        "smoke_test": bool(summary.get("smoke_test") or state.get("smoke_test")),
        "base_model": summary.get("base_model") or state.get("base_model") or "",
        "peft_method": summary.get("peft_method") or state.get("peft_method") or "",
        "start_ts": start_ts,
        "end_ts": summary.get("end_ts"),
        "duration_s": summary.get("duration_s"),
        "elapsed_s": elapsed_s,
        "stage": _derive_stage(status, state.get("current_step"),
                               summary.get("total_steps") or state.get("total_steps")),
        "total_steps": summary.get("total_steps") or (state.get("total_steps") or 0),
        "current_step": state.get("current_step"),
        "current_epoch": state.get("current_epoch"),
        "total_epochs": state.get("total_epochs"),
        "current_loss": state.get("current_loss"),
        "current_lr": state.get("current_lr"),
        "final_loss": summary.get("final_loss"),
        "best_eval_loss": summary.get("best_eval_loss"),
        "trainable_params": summary.get("trainable_params"),
        "total_params": summary.get("total_params"),
        "peak_vram_gb": summary.get("peak_vram_gb"),
        "pid": pid,
        "error": error,
    }
    if include_metrics:
        out["metrics"] = _read_metrics_rows(adapter_dir)
    return out


# ---------------------------------------------------------------------------
# train_status
# ---------------------------------------------------------------------------
class _Empty(BaseModel):
    pass


@tool(
    "train_status",
    description=(
        "Return the most recently active training run (if any) plus its "
        "live metrics. Use when the user asks 'how's training going?' or "
        "'is anything running?'. Renders as a live training card."
    ),
    args_model=_Empty,
)
async def train_status(args: _Empty, ctx: ToolContext) -> dict[str, Any]:
    # Consider both "running" (in the loop) and "starting" (just launched,
    # loading model/data) so the live card shows the whole lifecycle.
    candidates: list[tuple[float, Path]] = []
    for d in _candidate_adapter_dirs(ctx.repo_root):
        state = _safe_json(d / "training_state.json")
        summary = _safe_json(d / "training_summary.json")
        if summary:
            continue  # finished run — belongs in history, not the live card
        if state.get("status") in ("running", "starting"):
            last = state.get("last_update_ts") or state.get("start_ts")
            try:
                ts = datetime.fromisoformat(last).timestamp() if last else 0.0
            except (TypeError, ValueError):
                ts = 0.0
            candidates.append((ts, d))
    if not candidates:
        return {
            "kind": "live_training",
            "active": False,
            "message": "No active training run.",
        }
    candidates.sort(reverse=True)
    chosen = candidates[0][1]
    run = _serialise_run(chosen, repo=ctx.repo_root, include_metrics=True)
    # A run whose process already died reads as failed, not active.
    active = run["status"] in ("running", "starting", "stalled")
    return {"kind": "live_training", "active": active, "run": run,
            **({} if active else {"message": "Last run ended: "
                                  f"{run['status']}."})}


# ---------------------------------------------------------------------------
# train_history
# ---------------------------------------------------------------------------
class TrainHistoryArgs(BaseModel):
    include_metrics: bool = Field(
        default=False,
        description="If True, also embed the per-step metrics JSONL for each run.",
    )


@tool(
    "train_history",
    description=(
        "List all past training runs (newest first) with summary metrics. "
        "Use when the user asks to compare runs or to see what's been done."
    ),
    args_model=TrainHistoryArgs,
)
async def train_history(args: TrainHistoryArgs, ctx: ToolContext) -> dict[str, Any]:
    runs = [
        _serialise_run(d, repo=ctx.repo_root, include_metrics=args.include_metrics)
        for d in _candidate_adapter_dirs(ctx.repo_root)
    ]
    runs.sort(key=lambda r: r.get("start_ts") or "", reverse=True)
    return {"kind": "run_history", "runs": runs}


# ---------------------------------------------------------------------------
# train_get_run
# ---------------------------------------------------------------------------
class GetRunArgs(BaseModel):
    adapter_dir: str = Field(
        description="Path to the adapter directory, relative to the repo "
                    "(e.g. 'artifacts/adapter' or 'artifacts/adapter-smoke').",
    )


@tool(
    "train_get_run",
    description=(
        "Fetch the full detail of one training run including loss + LR curves "
        "(all metric rows from training_metrics.jsonl)."
    ),
    args_model=GetRunArgs,
)
async def train_get_run(args: GetRunArgs, ctx: ToolContext) -> dict[str, Any]:
    p = (ctx.repo_root / args.adapter_dir).resolve()
    if not str(p).startswith(str(ctx.repo_root)):
        raise ToolError("path escapes repo root")
    if not p.exists():
        raise ToolError(f"no such adapter: {args.adapter_dir}")
    return {
        "kind": "run_detail",
        "run": _serialise_run(p, repo=ctx.repo_root, include_metrics=True),
    }


# ---------------------------------------------------------------------------
# train_start
# ---------------------------------------------------------------------------
METHOD_MODULE = {
    "sft": "llmops.training.train_sft_lora",
    "dpo": "llmops.training.train_dpo",
    "kto": "llmops.training.train_kto",
    "reward": "llmops.training.train_reward",
    "grpo": "llmops.training.train_grpo",
    "rloo": "llmops.training.train_rloo",
}
METHOD_CONFIG = {
    "sft": "configs/train.yaml", "dpo": "configs/train_dpo.yaml",
    "kto": "configs/train_kto.yaml", "reward": "configs/train_reward.yaml",
    "grpo": "configs/train_grpo.yaml", "rloo": "configs/train_rloo.yaml",
}
# Non-smoke output dir per method (matches each trainer's config default).
METHOD_ADAPTER = {
    "sft": "adapter", "dpo": "dpo-adapter", "kto": "kto-adapter",
    "reward": "reward-model", "grpo": "grpo-adapter", "rloo": "rloo-adapter",
}


def _adapter_rel(method: str, smoke: bool) -> str:
    if smoke:
        return "adapter-smoke" if method == "sft" else f"{method}-smoke"
    return METHOD_ADAPTER.get(method, "adapter")


class TrainStartArgs(BaseModel):
    method: str = Field(
        default="sft",
        description="One of: sft, dpo, kto, reward, grpo, rloo.",
    )
    smoke: bool = Field(
        default=True,
        description="If True, run --smoke-test (CPU, tiny model, 2 steps, ~30s). "
                    "Always start with smoke before paying for full GPU time.",
    )
    config: str | None = Field(
        default=None,
        description="Override config path. Defaults to configs/train.yaml "
                    "for sft or configs/train_dpo.yaml for dpo.",
    )


@tool(
    "train_start",
    description=(
        "Launch a training run as a background subprocess. Returns the PID "
        "and adapter_dir immediately — the run keeps going if the user "
        "navigates away. Watch progress via train_status. "
        "ALWAYS smoke=true on the first run for a new dataset/config."
    ),
    args_model=TrainStartArgs,
    dangerous=True,
)
async def train_start(args: TrainStartArgs, ctx: ToolContext) -> dict[str, Any]:
    method = args.method.lower()
    if method not in METHOD_MODULE:
        raise ToolError(f"method must be one of {sorted(METHOD_MODULE)}")

    # Preflight: the training modules import trl/peft/accelerate at load time.
    # Without them the subprocess dies instantly and writes no run state, so
    # the run silently vanishes. Fail loudly and actionably instead.
    missing = _missing_training_deps()
    if missing:
        raise ToolError(
            "Training can't start: these Python packages are not installed ("
            f"{', '.join(missing)}). Install the training extras with "
            "`pip install -e \".[train]\"` (or from the Train page's "
            "Environment panel), then try again."
        )

    module = METHOD_MODULE[method]
    cfg_rel = args.config or METHOD_CONFIG[method]
    cfg = (ctx.repo_root / cfg_rel).resolve()
    if not cfg.exists():
        raise ToolError(f"config not found: {cfg_rel}")

    adapter_dir = ctx.repo_root / "artifacts" / _adapter_rel(method, args.smoke)

    cmd = [sys.executable, "-m", module, "--config", str(cfg)]
    if args.smoke:
        cmd.append("--smoke-test")

    logs = ctx.repo_root / "artifacts" / "copilot" / "training-logs"
    logs.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    log_path = logs / f"{method}_{ts}.log"

    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")

    log_fh = log_path.open("wb")
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(ctx.repo_root), env=env,
        stdout=log_fh, stderr=asyncio.subprocess.STDOUT,
        start_new_session=os.name != "nt",
    )
    # Don't close the log file handle — subprocess owns it now. Track for GC.
    proc._puffin_log_fh = log_fh  # type: ignore[attr-defined]

    # Write an initial run record so the run shows up in history and the live
    # card immediately — before the training loop writes its own state. The
    # loop overwrites this on its first step; if it never gets there (crash),
    # the dead-PID check flips this to "failed" so the run doesn't vanish.
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    log_rel = str(log_path.relative_to(ctx.repo_root)).replace("\\", "/")
    adapter_dir.mkdir(parents=True, exist_ok=True)
    try:
        # Durable pointer to the log (the metrics callback rewrites
        # training_state.json every step and would drop log_path otherwise).
        (adapter_dir / ".log_path").write_text(log_rel, encoding="utf-8")
        # Reproducibility: snapshot the exact config this run used, so the run
        # dir alone answers "what settings produced this adapter?".
        try:
            (adapter_dir / "run_config.yaml").write_text(
                cfg.read_text(encoding="utf-8"), encoding="utf-8")
        except OSError:
            pass
        # Durable reproducibility metadata: which data (fingerprint) + config
        # produced this run. The trainer rewrites training_state.json every
        # step, so this lives in its own file that nothing else touches.
        dataset_hash: str | None = None
        try:
            from copilot.backend.data_inspect import dataset_fingerprint
            fp = dataset_fingerprint(ctx.repo_root)
            dataset_hash = fp.get("dataset_hash")
            (adapter_dir / "run_meta.json").write_text(json.dumps({
                "launched_at": now,
                "method": method,
                "smoke_test": args.smoke,
                "config_snapshot": "run_config.yaml",
                "config_source": str(cfg.relative_to(ctx.repo_root)).replace("\\", "/"),
                "dataset_hash": dataset_hash,
                "dataset_splits": fp.get("splits", {}),
                "command": " ".join(cmd),
            }, indent=2), encoding="utf-8")
        except Exception:  # noqa: BLE001 - metadata is best-effort
            pass
        (adapter_dir / "training_state.json").write_text(json.dumps({
            "status": "starting",
            "method": method,
            "smoke_test": args.smoke,
            "pid": proc.pid,
            "start_ts": now,
            "last_update_ts": now,
            "current_step": None,
            "total_steps": None,
            "log_path": log_rel,
        }), encoding="utf-8")
    except OSError:
        pass

    return {
        "kind": "train_started",
        "method": method,
        "smoke": args.smoke,
        "pid": proc.pid,
        "adapter_dir": str(adapter_dir.relative_to(ctx.repo_root)),
        "log_path": str(log_path.relative_to(ctx.repo_root)),
        "command": " ".join(cmd),
        "message": (
            f"Started {'smoke ' if args.smoke else ''}{method.upper()} training "
            f"(PID {proc.pid}). Watch progress on the Monitor → Live training tab, "
            "or ask 'how's training going?'."
        ),
    }


# ---------------------------------------------------------------------------
# train_cancel
# ---------------------------------------------------------------------------
class TrainCancelArgs(BaseModel):
    pid: int = Field(description="PID returned by train_start.")


@tool(
    "train_cancel",
    description="Stop a training subprocess by PID (sends SIGTERM, escalates to SIGKILL).",
    args_model=TrainCancelArgs,
    dangerous=True,
)
async def train_cancel(args: TrainCancelArgs, ctx: ToolContext) -> dict[str, Any]:
    pid = args.pid
    try:
        if os.name == "nt":
            os.kill(pid, signal.SIGTERM)
        else:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
    except ProcessLookupError:
        return {"kind": "train_cancel_result", "pid": pid, "killed": False,
                "message": "No such process."}
    except PermissionError:
        return {"kind": "train_cancel_result", "pid": pid, "killed": False,
                "message": "Permission denied."}
    return {"kind": "train_cancel_result", "pid": pid, "killed": True,
            "message": f"Sent SIGTERM to PID {pid}."}
