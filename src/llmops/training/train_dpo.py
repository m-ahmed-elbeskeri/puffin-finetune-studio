"""DPO training (TRL + PEFT + optional unsloth).

CLI:
    python -m llmops.training.train_dpo --config configs/train_dpo.yaml

Expects preference data at `data.train_path` / `data.eval_path` with the schema
defined in `data_contracts/preference_schema.json`:
    { "prompt": ..., "chosen": ..., "rejected": ... }

Shares the engine / quantization / attention / PEFT / optimizer knob surface with
`train_sft_lora.py`. DPO-specific additions:
- beta (preference strength, default 0.1)
- loss_type: sigmoid | hinge | ipo | exo_pair | nca_pair | robust | bco_pair |
             sppo_hard | aot | aot_unpaired | apo_zero | apo_down | discopop |
             sft | sigmoid_norm
- loss_weights (list, for multi-loss MPO: e.g. ["sigmoid", "bco_pair", "sft"] with [0.8, 0.2, 1.0])
- label_smoothing (for cDPO / Robust DPO)
- sync_ref_model + precompute_ref_log_probs (memory tradeoffs)
- use_liger_kernel
"""

from __future__ import annotations

import argparse
import inspect
import json
import sys
from pathlib import Path
from typing import Any

from llmops.common.config import config_hash, flatten, load_yaml
from llmops.common.logging import get_logger
from llmops.common.tracking import get_tracker
from llmops.common.versioning import run_identity
from llmops.data.io_utils import read_jsonl
from llmops.features.chat_template import DEFAULT_CHAT_TEMPLATE_VERSION, get_chat_template
from llmops.training._metrics_callback import TrainingMetricsCallback
from llmops.training.train_sft_lora import (
    ConfigValidationError,
    _build_peft_config,
    _load_model_and_tokenizer,
    _normalize_report_to,
    _print_effective_config,
    _validate_config,
    _wrap_with_peft,
)

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# DPO-specific validation
# ---------------------------------------------------------------------------
def _validate_dpo_config(cfg: dict[str, Any]) -> None:
    """DPO-specific guardrails layered on top of _validate_config.

    Catches the combos TRL's DPOTrainer explicitly rejects, before we hit them
    at runtime. Always actionable.
    """
    dpo_cfg = cfg.get("dpo") or {}
    train_cfg = cfg.get("training") or {}
    lora_cfg = cfg.get("lora") or {}
    data_cfg = cfg.get("data") or {}

    loss_type = dpo_cfg.get("loss_type", "sigmoid")
    is_multi_loss = isinstance(loss_type, list)
    label_smoothing = float(dpo_cfg.get("label_smoothing", 0.0))

    # 1. exo_pair requires label_smoothing > 0
    bad_loss_for_smoothing = (
        ("exo_pair" in loss_type) if is_multi_loss else (loss_type == "exo_pair")
    )
    if bad_loss_for_smoothing and label_smoothing <= 0.0:
        raise ConfigValidationError(
            "dpo.loss_type='exo_pair' requires dpo.label_smoothing > 0 (1e-3 recommended). "
            f"Got label_smoothing={label_smoothing}."
        )

    # 2. robust loss must have 0 < label_smoothing < 0.5
    is_robust = ("robust" in loss_type) if is_multi_loss else (loss_type == "robust")
    if is_robust and not (0.0 < label_smoothing < 0.5):
        raise ConfigValidationError(
            "dpo.loss_type='robust' requires 0 < dpo.label_smoothing < 0.5 "
            f"(it represents the label-flip probability). Got {label_smoothing}."
        )

    # 3. multi-loss list lengths must match
    loss_weights = dpo_cfg.get("loss_weights")
    if is_multi_loss and loss_weights is not None and len(loss_weights) != len(loss_type):
        raise ConfigValidationError(
            f"dpo.loss_weights has {len(loss_weights)} entries but "
            f"dpo.loss_type has {len(loss_type)}. They must be the same length."
        )

    # 4. use_liger_kernel with DPO has restrictions
    if train_cfg.get("use_liger_kernel"):
        if is_multi_loss:
            raise ConfigValidationError(
                "DPO with training.use_liger_kernel=true does NOT support multi-loss "
                "(loss_type as a list). Use a single loss_type or disable Liger."
            )
        if dpo_cfg.get("precompute_ref_log_probs"):
            raise ConfigValidationError(
                "DPO with training.use_liger_kernel=true does NOT support "
                "dpo.precompute_ref_log_probs=true. Choose one."
            )

    # 5. aot loss types don't work with use_weighting=true
    has_aot = any(
        lt in ("aot", "aot_unpaired") for lt in (loss_type if is_multi_loss else [loss_type])
    )
    if has_aot and dpo_cfg.get("use_weighting"):
        raise ConfigValidationError(
            "dpo.loss_type 'aot'/'aot_unpaired' is incompatible with dpo.use_weighting=true. "
            "Pick one or use a different loss."
        )

    # 6. sync_ref_model + PEFT (no standalone ref_model) is unsupported by TRL
    using_peft = lora_cfg.get("enabled", True) and (lora_cfg.get("method") or "lora") != "none"
    if dpo_cfg.get("sync_ref_model") and using_peft:
        raise ConfigValidationError(
            "dpo.sync_ref_model=true is not supported when training with PEFT (LoRA/DoRA/...). "
            "Either disable LoRA (lora.enabled: false), pass an explicit ref_model in code, "
            "or turn sync_ref_model off."
        )

    # 7. sync_ref_model + precompute_ref_log_probs is mutually exclusive
    if dpo_cfg.get("sync_ref_model") and dpo_cfg.get("precompute_ref_log_probs"):
        raise ConfigValidationError(
            "dpo.sync_ref_model and dpo.precompute_ref_log_probs cannot both be true "
            "(the ref model keeps changing, so precomputed log-probs go stale). Pick one."
        )

    # 8. max_length must be > max_prompt_length (if both set)
    max_length = data_cfg.get("max_length")
    max_prompt_length = data_cfg.get("max_prompt_length")
    if max_length is not None and max_prompt_length is not None and max_prompt_length >= max_length:
        raise ConfigValidationError(
            f"data.max_prompt_length ({max_prompt_length}) must be strictly less than "
            f"data.max_length ({max_length}). The completion needs room to fit."
        )


# ---------------------------------------------------------------------------
# Smoke-test overrides
# ---------------------------------------------------------------------------
def _smoke_overrides(cfg: dict[str, Any]) -> dict[str, Any]:
    log.warning("SMOKE MODE: overriding DPO model + training settings for CPU smoke test")
    cfg.setdefault("model", {})
    cfg.setdefault("training", {})
    cfg.setdefault("dpo", {})
    cfg["model"]["base_model"] = cfg["model"].get(
        "smoke_base_model", "HuggingFaceTB/SmolLM2-135M-Instruct"
    )
    cfg["model"]["loader"] = "hf"
    cfg["model"]["quantization"] = None
    cfg["model"]["attn_impl"] = "eager"
    cfg["training"].update(
        {
            "epochs": 1,
            "per_device_train_batch_size": 1,
            "gradient_accumulation_steps": 1,
            "max_steps": 2,
            "logging_steps": 1,
            "save_strategy": "no",
            "eval_strategy": "no",
            "bf16": False,
            "fp16": False,
            "gradient_checkpointing": False,
            "learning_rate": 5.0e-5,
            "report_to": "none",
            "use_liger_kernel": False,
        }
    )
    cfg.setdefault("data", {}).update({"limit": 4, "max_length": 256})
    cfg.setdefault("lora", {}).update(
        {
            "r": 4,
            "alpha": 8,
            "dropout": 0.0,
            "method": "lora",
            "use_dora": False,
            "use_rslora": False,
        }
    )
    cfg.setdefault("output", {}).update({"adapter_dir": "artifacts/dpo-smoke"})
    return cfg


def _load_pref_dataset(path: str | Path, *, limit: int | None = None) -> Any:
    from datasets import Dataset

    rows = []
    for r in read_jsonl(path):
        if not all(k in r for k in ("prompt", "chosen", "rejected")):
            continue
        rows.append({"prompt": r["prompt"], "chosen": r["chosen"], "rejected": r["rejected"]})
    if limit is not None:
        rows = rows[:limit]
    return Dataset.from_list(rows)


# ---------------------------------------------------------------------------
# DPOConfig builder
# ---------------------------------------------------------------------------
_DPO_LOSS_TYPES = {
    "sigmoid",
    "hinge",
    "ipo",
    "exo_pair",
    "nca_pair",
    "robust",
    "bco_pair",
    "sppo_hard",
    "aot",
    "aot_unpaired",
    "apo_zero",
    "apo_down",
    "discopop",
    "sft",
    "sigmoid_norm",
}


def _build_dpo_args(cfg: dict[str, Any], output_dir: Path) -> Any:
    import torch
    from trl import DPOConfig

    train_cfg = cfg["training"]
    data_cfg = cfg["data"]
    dpo_cfg = cfg.get("dpo", {})

    dpo_params = inspect.signature(DPOConfig.__init__).parameters

    args_kwargs: dict[str, Any] = {
        "output_dir": str(output_dir),
        "num_train_epochs": float(train_cfg.get("epochs", 1)),
        "learning_rate": float(train_cfg.get("learning_rate", 5.0e-6)),
        "weight_decay": float(train_cfg.get("weight_decay", 0.0)),
        "warmup_ratio": float(train_cfg.get("warmup_ratio", 0.0)),
        "lr_scheduler_type": str(train_cfg.get("lr_scheduler_type", "linear")),
        "per_device_train_batch_size": int(train_cfg.get("per_device_train_batch_size", 2)),
        "gradient_accumulation_steps": int(train_cfg.get("gradient_accumulation_steps", 8)),
        "max_grad_norm": float(train_cfg.get("max_grad_norm", 1.0)),
        "optim": str(train_cfg.get("optim", "adamw_torch")),
        "bf16": bool(train_cfg.get("bf16", False)) and torch.cuda.is_available(),
        "fp16": bool(train_cfg.get("fp16", False)) and torch.cuda.is_available(),
        "gradient_checkpointing": bool(train_cfg.get("gradient_checkpointing", True)),
        "seed": int(train_cfg.get("seed", 42)),
        "eval_strategy": train_cfg.get("eval_strategy", "no"),
        "save_strategy": train_cfg.get("save_strategy", "epoch"),
        "logging_steps": int(train_cfg.get("logging_steps", 10)),
        "save_total_limit": int(train_cfg.get("save_total_limit", 3)),
        "report_to": _normalize_report_to(train_cfg.get("report_to")),
        "max_length": int(data_cfg.get("max_length", 1024)),
        "beta": float(dpo_cfg.get("beta", 0.1)),
    }

    # DPO loss configuration. Supports single loss or multi-loss (MPO) list.
    loss_type = dpo_cfg.get("loss_type", "sigmoid")
    loss_weights = dpo_cfg.get("loss_weights")
    if isinstance(loss_type, list):
        for lt in loss_type:
            if lt not in _DPO_LOSS_TYPES:
                raise ValueError(f"Unknown DPO loss_type {lt!r}. Valid: {sorted(_DPO_LOSS_TYPES)}")
    else:
        if loss_type not in _DPO_LOSS_TYPES:
            raise ValueError(
                f"Unknown DPO loss_type {loss_type!r}. Valid: {sorted(_DPO_LOSS_TYPES)}"
            )
    args_kwargs["loss_type"] = loss_type
    if loss_weights is not None and "loss_weights" in dpo_params:
        args_kwargs["loss_weights"] = loss_weights
    if "label_smoothing" in dpo_params and "label_smoothing" in dpo_cfg:
        args_kwargs["label_smoothing"] = float(dpo_cfg["label_smoothing"])

    if "max_steps" in train_cfg:
        args_kwargs["max_steps"] = int(train_cfg["max_steps"])

    # Optional DPO-specific knobs (set only if the TRL version supports them).
    opt_knobs = {
        "max_prompt_length": data_cfg.get("max_prompt_length"),
        "sync_ref_model": dpo_cfg.get("sync_ref_model"),
        "precompute_ref_log_probs": dpo_cfg.get("precompute_ref_log_probs"),
        "use_weighting": dpo_cfg.get("use_weighting"),
        "use_liger_kernel": train_cfg.get("use_liger_kernel"),
    }
    for k, v in opt_knobs.items():
        if v is None:
            continue
        if k in dpo_params:
            args_kwargs[k] = v
        else:
            log.warning("DPOConfig has no %r in this TRL version; ignoring.", k)

    gc_kwargs = train_cfg.get("gradient_checkpointing_kwargs")
    if gc_kwargs and "gradient_checkpointing_kwargs" in dpo_params:
        args_kwargs["gradient_checkpointing_kwargs"] = gc_kwargs

    return DPOConfig(**args_kwargs)


# ---------------------------------------------------------------------------
# Train entry point
# ---------------------------------------------------------------------------
def train(cfg: dict[str, Any], *, smoke_test: bool = False) -> Path:
    if smoke_test:
        cfg = _smoke_overrides(dict(cfg))

    # Fail-fast validation BEFORE expensive model load.
    _validate_config(cfg)
    _validate_dpo_config(cfg)
    _print_effective_config(cfg)

    from trl import DPOTrainer

    model_cfg = cfg["model"]
    train_cfg = cfg["training"]
    lora_cfg = cfg.get("lora", {})
    data_cfg = cfg["data"]
    output_cfg = cfg.get("output", {})
    chat_tpl_version = data_cfg.get("chat_template_version", DEFAULT_CHAT_TEMPLATE_VERSION)

    # Model + tokenizer (engine-aware, shared with SFT)
    model, tokenizer = _load_model_and_tokenizer(model_cfg, train_cfg)
    tokenizer.chat_template = get_chat_template(chat_tpl_version)

    # PEFT
    loader = (model_cfg.get("loader") or "hf").lower()
    peft_config = _build_peft_config(lora_cfg)
    # DPO+PEFT trick: pass peft_config to the trainer itself rather than pre-wrapping,
    # since DPOTrainer can construct the ref model from the unwrapped base model.
    # If unsloth, we still pre-wrap (unsloth's PEFT path is the LoRA injector).
    if loader == "unsloth" and peft_config is not None:
        model = _wrap_with_peft(model, peft_config, lora_cfg, loader)
        trainer_peft_config = None
    else:
        trainer_peft_config = peft_config

    # Dataset
    train_ds = _load_pref_dataset(data_cfg["train_path"], limit=data_cfg.get("limit"))
    eval_ds = (
        _load_pref_dataset(data_cfg["eval_path"], limit=data_cfg.get("limit"))
        if data_cfg.get("eval_path")
        else None
    )

    output_dir = Path(output_cfg.get("adapter_dir", "artifacts/dpo-adapter"))
    output_dir.mkdir(parents=True, exist_ok=True)
    args = _build_dpo_args(cfg, output_dir)

    tracker_cfg = cfg.get("tracking", {})
    tracker = get_tracker(tracker_cfg.get("backend"))
    if tracker_cfg.get("experiment_name"):
        tracker.set_experiment(tracker_cfg["experiment_name"])

    run_name = cfg.get("run_name", "puffin-dpo")
    config_h = config_hash(cfg)
    identity = run_identity()

    with tracker.start_run(run_name=run_name) as _run:
        tracker.log_params(flatten({**cfg, "_config_hash": config_h}))
        tracker.set_tags(
            {
                "method": "dpo",
                "config_hash": config_h,
                "loader": loader,
                "attn_impl": model_cfg.get("attn_impl", "sdpa"),
                "peft_method": (lora_cfg.get("method") or "lora")
                if lora_cfg.get("enabled", True)
                else "full",
                "dpo_loss": str(cfg.get("dpo", {}).get("loss_type", "sigmoid")),
                "git_sha": identity.get("git_sha") or "n/a",
                "platform": identity.get("platform"),
            }
        )

        dpo_params = inspect.signature(DPOTrainer.__init__).parameters
        tok_kwarg = "processing_class" if "processing_class" in dpo_params else "tokenizer"
        metrics_cb = TrainingMetricsCallback(
            output_dir=output_dir,
            method="dpo",
            run_name=run_name,
            smoke_test=smoke_test,
            base_model=model_cfg["base_model"],
            peft_method=(
                (lora_cfg.get("method") or "lora") if lora_cfg.get("enabled", True) else "full"
            ),
        )
        trainer = DPOTrainer(
            model=model,
            ref_model=None,
            args=args,
            train_dataset=train_ds,
            eval_dataset=eval_ds,
            peft_config=trainer_peft_config,
            callbacks=[metrics_cb],
            **{tok_kwarg: tokenizer},
        )
        try:
            trainer.train()
        except BaseException as exc:
            metrics_cb.mark_failed(f"{type(exc).__name__}: {exc}", state=trainer.state)
            raise
        trainer.save_model(str(output_dir))
        tokenizer.save_pretrained(str(output_dir))

        (output_dir / "lineage.json").write_text(
            json.dumps(
                {
                    "method": "dpo",
                    "config_hash": config_h,
                    "base_model": model_cfg["base_model"],
                    "loader": loader,
                    "attn_impl": model_cfg.get("attn_impl", "sdpa"),
                    "peft_method": lora_cfg.get("method", "lora"),
                    "dpo_loss": cfg.get("dpo", {}).get("loss_type", "sigmoid"),
                    "smoke_test": smoke_test,
                    "identity": identity,
                    "config": cfg,
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

        history = getattr(trainer.state, "log_history", [])
        if history:
            last = history[-1]
            metrics = {k: float(v) for k, v in last.items() if isinstance(v, (int, float))}
            if metrics:
                tracker.log_metrics(metrics)
        tracker.log_artifacts(str(output_dir))

    log.info("DPO training complete; saved to %s", output_dir)
    return output_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DPO training.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args(argv)
    cfg = load_yaml(args.config)
    train(cfg, smoke_test=args.smoke_test)
    return 0


if __name__ == "__main__":
    sys.exit(main())
