"""Live-tailable training metrics sidecar.

A TrainerCallback that writes three files next to the adapter output dir, so
the UI (and any other consumer) can both watch a run live and inspect past
runs without depending on MLflow.

Files written (all in the trainer's `output_dir`):

  training_metrics.jsonl
      One JSON object per HF log event. Fields are whatever the trainer
      emits (loss, learning_rate, grad_norm, epoch, step, eval_loss, ...)
      plus `ts` (wall-clock ISO 8601).

  training_state.json
      Single-object file rewritten on every log/step.
        status:        "running" | "completed" | "failed"
        method:        "sft" | "dpo" | ...   (set by the trainer caller)
        run_name:      identifier (cfg.run_name)
        smoke_test:    bool
        pid:           os.getpid()
        start_ts:      ISO 8601
        last_update_ts: ISO 8601
        current_step:  int
        total_steps:   int | null
        current_epoch: float
        total_epochs:  float
        current_loss:  float | null  (last training loss)
        current_lr:    float | null
        error:         str | null

  training_summary.json
      Written once at on_train_end. Stable, queryable summary:
        status, method, run_name, smoke_test
        start_ts, end_ts, duration_s
        total_steps, final_loss, best_eval_loss
        trainable_params, total_params, peak_vram_gb
        base_model, peft_method
        adapter_dir

The callback never raises into the trainer — every write is wrapped in a
contextlib.suppress so a flaky filesystem can't kill a run.
"""

from __future__ import annotations

import contextlib
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from transformers import TrainerCallback
except ImportError:  # pragma: no cover - trainer always present when used
    TrainerCallback = object  # type: ignore[misc, assignment]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def _atomic_write(path: Path, data: str) -> None:
    """Write `data` to `path` atomically (write to .tmp, then replace)."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(data, encoding="utf-8")
    os.replace(tmp, path)


def _peak_vram_gb() -> float | None:
    """Peak CUDA memory used (GB) across all visible GPUs, or None on CPU."""
    try:
        import torch  # local import: trainer always has torch

        if not torch.cuda.is_available():
            return None
        total = 0
        for i in range(torch.cuda.device_count()):
            total += torch.cuda.max_memory_allocated(i)
        return round(total / (1024**3), 3)
    except Exception:
        return None


def _count_params(model: Any) -> tuple[int, int]:
    """Return (trainable, total) parameter counts. Best-effort."""
    try:
        total = sum(p.numel() for p in model.parameters())
        trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
        return trainable, total
    except Exception:
        return 0, 0


class TrainingMetricsCallback(TrainerCallback):
    """Persist live + post-run metrics to JSON sidecars in the output dir.

    Args:
        output_dir: where to write the sidecars (same as trainer's output_dir).
        method:    "sft" / "dpo" / ... — surfaced in the JSON for UI grouping.
        run_name:  human label, from cfg.run_name.
        smoke_test: if True the UI shows a "smoke" badge.
        base_model: model id for the summary.
        peft_method: lora / dora / full / ... for the summary.
    """

    # The callback intentionally keeps no torch state; only file IO + ints.
    def __init__(
        self,
        *,
        output_dir: Path,
        method: str,
        run_name: str,
        smoke_test: bool,
        base_model: str,
        peft_method: str,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.method = method
        self.run_name = run_name
        self.smoke_test = bool(smoke_test)
        self.base_model = base_model
        self.peft_method = peft_method

        self.metrics_path = self.output_dir / "training_metrics.jsonl"
        self.state_path = self.output_dir / "training_state.json"
        self.summary_path = self.output_dir / "training_summary.json"

        self.start_ts: str | None = None
        self.start_perf: float | None = None
        self.last_loss: float | None = None
        self.last_lr: float | None = None
        self.best_eval_loss: float | None = None
        self.trainable_params: int = 0
        self.total_params: int = 0

    # ------------------------------------------------------------------
    # Lifecycle hooks
    # ------------------------------------------------------------------
    def on_train_begin(self, args, state, control, **kwargs):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        # Truncate the JSONL so each run starts clean.
        with contextlib.suppress(OSError):
            self.metrics_path.write_text("", encoding="utf-8")

        self.start_ts = _now_iso()
        self.start_perf = time.perf_counter()

        model = kwargs.get("model")
        if model is not None:
            self.trainable_params, self.total_params = _count_params(model)

        self._write_state(
            status="running",
            state=state,
            error=None,
            extra={"total_steps": int(getattr(state, "max_steps", 0) or 0)},
        )
        return control

    def on_log(self, args, state, control, logs=None, **kwargs):
        logs = dict(logs or {})
        if not logs:
            return control

        # HF emits two log kinds: train ({loss, learning_rate, grad_norm,
        # epoch}) and eval ({eval_loss, eval_runtime, ...}). Both carry the
        # global step on `state`.
        row: dict[str, Any] = {"ts": _now_iso(), "step": int(state.global_step)}
        for k, v in logs.items():
            if isinstance(v, (int, float, str, bool)):
                row[k] = v

        # Track best eval loss for the summary.
        if "eval_loss" in row:
            try:
                e = float(row["eval_loss"])
                self.best_eval_loss = (
                    e if self.best_eval_loss is None else min(self.best_eval_loss, e)
                )
            except (TypeError, ValueError):
                pass

        # Track last train loss + lr for the live state file.
        if "loss" in row:
            with contextlib.suppress(TypeError, ValueError):
                self.last_loss = float(row["loss"])
        if "learning_rate" in row:
            with contextlib.suppress(TypeError, ValueError):
                self.last_lr = float(row["learning_rate"])

        with contextlib.suppress(OSError), self.metrics_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str) + "\n")

        self._write_state(status="running", state=state, error=None)
        return control

    def on_step_end(self, args, state, control, **kwargs):
        # Lightweight progress ping so the UI's progress bar updates even
        # between logging_steps boundaries.
        self._write_state(status="running", state=state, error=None)
        return control

    def on_train_end(self, args, state, control, **kwargs):
        end_ts = _now_iso()
        duration_s = (
            round(time.perf_counter() - self.start_perf, 2) if self.start_perf is not None else None
        )
        # Final train loss: prefer the trainer's accumulated history,
        # otherwise fall back to whatever we last saw.
        final_loss = self.last_loss
        for row in reversed(getattr(state, "log_history", []) or []):
            if "loss" in row:
                with contextlib.suppress(TypeError, ValueError):
                    final_loss = float(row["loss"])
                break

        summary = {
            "status": "completed",
            "method": self.method,
            "run_name": self.run_name,
            "smoke_test": self.smoke_test,
            "base_model": self.base_model,
            "peft_method": self.peft_method,
            "start_ts": self.start_ts,
            "end_ts": end_ts,
            "duration_s": duration_s,
            "total_steps": int(state.global_step),
            "final_loss": final_loss,
            "best_eval_loss": self.best_eval_loss,
            "trainable_params": self.trainable_params,
            "total_params": self.total_params,
            "peak_vram_gb": _peak_vram_gb(),
            "adapter_dir": str(self.output_dir),
        }
        with contextlib.suppress(OSError):
            _atomic_write(self.summary_path, json.dumps(summary, indent=2, default=str))

        # Mark state as completed; UI's Live tab will flip to "no active run".
        self._write_state(
            status="completed",
            state=state,
            error=None,
            extra={"end_ts": end_ts, "duration_s": duration_s},
        )
        return control

    # ------------------------------------------------------------------
    # Failure path — called from the trainer wrapper, not by HF.
    # ------------------------------------------------------------------
    def mark_failed(self, error: str, state: Any | None = None) -> None:
        end_ts = _now_iso()
        duration_s = (
            round(time.perf_counter() - self.start_perf, 2) if self.start_perf is not None else None
        )
        summary = {
            "status": "failed",
            "method": self.method,
            "run_name": self.run_name,
            "smoke_test": self.smoke_test,
            "base_model": self.base_model,
            "peft_method": self.peft_method,
            "start_ts": self.start_ts,
            "end_ts": end_ts,
            "duration_s": duration_s,
            "total_steps": int(getattr(state, "global_step", 0) or 0),
            "final_loss": self.last_loss,
            "best_eval_loss": self.best_eval_loss,
            "trainable_params": self.trainable_params,
            "total_params": self.total_params,
            "peak_vram_gb": _peak_vram_gb(),
            "adapter_dir": str(self.output_dir),
            "error": error,
        }
        with contextlib.suppress(OSError):
            _atomic_write(self.summary_path, json.dumps(summary, indent=2, default=str))
        self._write_state(status="failed", state=state, error=error)

    # ------------------------------------------------------------------
    # Internal: state file writer
    # ------------------------------------------------------------------
    def _write_state(
        self,
        *,
        status: str,
        state: Any | None,
        error: str | None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        body: dict[str, Any] = {
            "status": status,
            "method": self.method,
            "run_name": self.run_name,
            "smoke_test": self.smoke_test,
            "base_model": self.base_model,
            "peft_method": self.peft_method,
            "pid": os.getpid(),
            "start_ts": self.start_ts,
            "last_update_ts": _now_iso(),
            "current_step": int(getattr(state, "global_step", 0) or 0),
            "total_steps": int(getattr(state, "max_steps", 0) or 0) or None,
            "current_epoch": float(getattr(state, "epoch", 0.0) or 0.0),
            "total_epochs": float(getattr(state, "num_train_epochs", 0.0) or 0.0),
            "current_loss": self.last_loss,
            "current_lr": self.last_lr,
            "error": error,
        }
        if extra:
            body.update(extra)
        with contextlib.suppress(OSError):
            _atomic_write(self.state_path, json.dumps(body, default=str))
