"""Pre-launch preflight checks and a rough resource estimate.

These answer the two questions you should ask before spending GPU time:
"will this even start?" (preflight) and "will it fit / how big is it?"
(estimate). Both work off the materialized config, so what you check is what
you'd launch.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from copilot.backend.training_studio import StudioError, _get_dotted, materialize
from copilot.backend.tools.train import _missing_training_deps


def _count_lines(p: Path) -> int:
    n = 0
    with p.open("rb") as fh:
        for _ in fh:
            n += 1
    return n


def _first_record(p: Path) -> dict[str, Any] | None:
    try:
        with p.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    obj = json.loads(line)
                    return obj if isinstance(obj, dict) else None
    except (OSError, json.JSONDecodeError):
        return None
    return None


def _data_train_path(cfg: dict[str, Any], method: str) -> str:
    for dotted in ("data.train_path", "dpo.train_path", "dataset.train_path",
                   "train_path"):
        v = _get_dotted(cfg, dotted)
        if isinstance(v, str) and v:
            return v
    return ("data/processed/preference_train.jsonl" if method == "dpo"
            else "data/processed/train.jsonl")


def _check(cid: str, label: str, status: str, detail: str) -> dict[str, Any]:
    return {"id": cid, "label": label, "status": status, "detail": detail}


def preflight(
    repo_root: Path, *, method: str,
    recipe_id: str | None = None, overrides: dict[str, Any] | None = None,
    local: bool = True,
) -> dict[str, Any]:
    """Catch the doomed launches: invalid config, missing deps, no/wrong data,
    empty base model. Returns typed checks the UI renders as a readiness list."""
    checks: list[dict[str, Any]] = []
    try:
        _rel, text = materialize(
            repo_root, method=method, recipe_id=recipe_id,
            overrides=overrides or {}, write=False)
        cfg = yaml.safe_load(text) or {}
    except StudioError as exc:
        return {"kind": "train_preflight", "ok": False,
                "checks": [_check("config", "Config is valid", "fail", str(exc))]}
    checks.append(_check("config", "Config is valid", "ok",
                         "Recipe and overrides validate against the knob schema."))

    # Dependencies (local only — cloud installs them in the job image).
    if local:
        missing = _missing_training_deps()
        if missing:
            checks.append(_check(
                "deps", "Training packages installed", "fail",
                f"Missing: {', '.join(missing)}. Install the training packages "
                "in the launch card below."))
        else:
            checks.append(_check("deps", "Training packages installed", "ok",
                                 "trl, peft, and accelerate are importable."))

    # Base model set.
    base = _get_dotted(cfg, "model.base_model")
    if not base:
        checks.append(_check("model", "Base model set", "fail",
                             "model.base_model is empty."))
    else:
        checks.append(_check("model", "Base model set", "ok", str(base)))

    # Training data present and the right shape for the method.
    rel = _data_train_path(cfg, method)
    p = (Path(repo_root) / rel).resolve()
    if not p.exists():
        checks.append(_check(
            "data", "Training data present", "fail",
            f"{rel} does not exist. This method needs {_DATA_HINT.get(method, 'training data')}; "
            "create it on the Data page."))
    else:
        n = _count_lines(p)
        rec = _first_record(p)
        shape = _data_shape_check(method, rec)
        if n == 0:
            checks.append(_check("data", "Training data present", "fail",
                                 f"{rel} is empty."))
        elif shape is not None:
            status, detail = shape
            checks.append(_check("data", "Data matches the method", status,
                                 detail.format(rel=rel)))
        else:
            checks.append(_check("data", "Training data present", "ok",
                                 f"{rel}: {n:,} records."))

    ok = not any(c["status"] == "fail" for c in checks)
    return {"kind": "train_preflight", "ok": ok, "checks": checks}


_DATA_HINT = {
    "sft": "chat or prompt/completion examples",
    "dpo": "preference pairs (prompt, chosen, rejected)",
    "reward": "preference pairs (chosen, rejected)",
    "kto": "unpaired rows (prompt, completion, boolean label)",
    "grpo": "prompts (the model samples completions)",
    "rloo": "prompts (the model samples completions)",
}


def _data_shape_check(method: str, rec: dict[str, Any] | None):
    """Return (status, detail-template) if the first row looks wrong for the
    method, else None. detail is formatted with {rel}."""
    if rec is None:
        return None
    if method in ("dpo", "reward"):
        if not ("chosen" in rec and "rejected" in rec):
            return ("fail", "{rel} has no chosen/rejected fields. This method "
                    "needs preference pairs; point at preference data or switch method.")
    elif method == "kto":
        if not ("prompt" in rec and "completion" in rec and "label" in rec):
            return ("fail", "{rel} rows need prompt, completion, and a boolean "
                    "label for KTO.")
    elif method in ("grpo", "rloo"):
        if not ("prompt" in rec or "messages" in rec):
            return ("fail", "{rel} rows need a prompt; online RL samples "
                    "completions from prompts.")
    elif method == "sft":
        if not ("messages" in rec or "prompt" in rec or "text" in rec):
            return ("warn", "{rel} rows don't look like chat/prompt records; "
                    "training may reject them. Audit the file on the Data page.")
    return None


# --------------------------------------------------------------------------
# Resource estimate
# --------------------------------------------------------------------------
def _params_billions(model_name: str) -> float | None:
    """Parse a parameter count from a model id, e.g. Llama-3.1-8B -> 8.0,
    SmolLM2-135M -> 0.135. Returns None if it can't be inferred."""
    if not model_name:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*([bm])\b", model_name.lower())
    if not m:
        return None
    n = float(m.group(1))
    return n if m.group(2) == "b" else n / 1000.0


def _quant_bytes(cfg: dict[str, Any]) -> tuple[float, str]:
    q = _get_dotted(cfg, "model.quantization")
    if isinstance(q, dict):
        if q.get("load_in_4bit"):
            return 0.5, "4-bit (QLoRA)"
        if q.get("load_in_8bit"):
            return 1.0, "8-bit"
    return 2.0, "bf16/fp16"


def estimate(
    repo_root: Path, *, method: str,
    recipe_id: str | None = None, overrides: dict[str, Any] | None = None,
    gpu: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Rough VRAM footprint from model size + config. Directional, not exact,
    but enough to catch an OOM before you hit it."""
    try:
        _rel, text = materialize(
            repo_root, method=method, recipe_id=recipe_id,
            overrides=overrides or {}, write=False)
        cfg = yaml.safe_load(text) or {}
    except StudioError:
        return {"kind": "train_estimate", "known": False,
                "note": "Fix the config to see an estimate."}

    base = str(_get_dotted(cfg, "model.base_model") or "")
    params_b = _params_billions(base)
    bytes_per_param, quant_label = _quant_bytes(cfg)
    # LoRA-first studio: default to LoRA unless the config explicitly disables
    # it. (You can't full fine-tune a quantized base anyway.)
    raw_lora = _get_dotted(cfg, "lora.enabled")
    lora_enabled = True if raw_lora is None else bool(raw_lora)
    batch = int(_get_dotted(cfg, "training.per_device_train_batch_size") or 1)
    seq_len = int(_get_dotted(cfg, "data.max_seq_length") or 2048)
    grad_ckpt = bool(_get_dotted(cfg, "training.gradient_checkpointing"))

    warnings: list[str] = []
    if params_b is None:
        return {
            "kind": "train_estimate", "known": False,
            "base_model": base,
            "note": ("Couldn't infer the model size from its name, so no VRAM "
                     "estimate. Smoke-test first to be safe."),
        }

    act_gb = 2.0 * max(1, batch) * max(0.25, seq_len / 2048.0)
    if grad_ckpt:
        act_gb *= 0.5
    if lora_enabled:
        vram = params_b * bytes_per_param + act_gb + 1.0
        method_note = "LoRA: the base model is frozen; only small adapters train."
    else:
        vram = params_b * 16.0 * (0.7 if grad_ckpt else 1.0) + act_gb
        method_note = ("Full fine-tune: base weights + gradients + optimizer "
                       "states (roughly 16x the parameters).")
        if bytes_per_param < 2.0:
            warnings.append("Quantization is set but full fine-tuning trains all "
                            "weights, so the base can't stay quantized. Use LoRA "
                            "with quantization instead (QLoRA).")

    vram = round(vram, 1)
    gpu = gpu or {}
    gpu_vram = gpu.get("vram_total_gb")
    fits: bool | None = None
    if gpu.get("available") and isinstance(gpu_vram, (int, float)):
        fits = vram <= float(gpu_vram)
        if not fits:
            warnings.append(
                f"Estimated {vram} GB exceeds your GPU's {gpu_vram} GB. Try "
                "QLoRA (4-bit), a smaller batch, gradient checkpointing, or a "
                "shorter max_seq_length.")

    return {
        "kind": "train_estimate",
        "known": True,
        "base_model": base,
        "params_b": params_b,
        "quantization": quant_label,
        "lora": lora_enabled,
        "batch": batch,
        "seq_len": seq_len,
        "vram_gb": vram,
        "gpu_vram_gb": gpu_vram,
        "fits": fits,
        "method_note": method_note,
        "time_note": ("Smoke test finishes in about a minute. A full run scales "
                      "with your dataset size, epochs, and GPU throughput."),
        "warnings": warnings,
    }
