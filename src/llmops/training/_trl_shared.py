"""Shared scaffolding for the TRL preference / RL trainers.

KTO, reward modeling, GRPO, and RLOO all follow the same shape as the DPO
trainer: load the (shared) model + tokenizer, build a *Config (a subclass of
transformers TrainingArguments) from our YAML, wire the metrics callback, run,
and save a lineage sidecar. This module factors out the parts that are
identical so each trainer module stays small and consistent with train_dpo.
"""

from __future__ import annotations

import contextlib
import inspect
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from llmops.common.config import config_hash, flatten
from llmops.common.logging import get_logger
from llmops.common.tracking import get_tracker
from llmops.common.versioning import run_identity
from llmops.training._metrics_callback import TrainingMetricsCallback
from llmops.training.train_sft_lora import _normalize_report_to

log = get_logger(__name__)

SMOKE_MODEL = "HuggingFaceTB/SmolLM2-135M-Instruct"


def apply_smoke(
    cfg: dict[str, Any],
    adapter_dir: str,
    extra_training: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Shrink a config to a ~30s CPU smoke run: tiny model, 2 steps. Online-RL
    methods pass extra_training (e.g. a batch size that fits num_generations)."""
    cfg = dict(cfg)
    model = dict(cfg.get("model", {}))
    model.update(
        {"base_model": SMOKE_MODEL, "loader": "hf", "quantization": None, "attn_impl": "eager"}
    )
    cfg["model"] = model
    tc = dict(cfg.get("training", {}))
    tc.update(
        {
            "max_steps": 2,
            "epochs": 1,
            "per_device_train_batch_size": 1,
            "gradient_accumulation_steps": 1,
            "bf16": False,
            "fp16": False,
            "gradient_checkpointing": False,
            "save_strategy": "no",
            "logging_steps": 1,
        }
    )
    if extra_training:
        tc.update(extra_training)
    cfg["training"] = tc
    cfg.setdefault("output", {})["adapter_dir"] = adapter_dir
    return cfg


def common_config_kwargs(
    cfg: dict[str, Any],
    output_dir: Path,
    param_names: Any,
) -> dict[str, Any]:
    """The TrainingArguments-level kwargs every TRL *Config accepts, filtered to
    the ones this TRL version actually declares."""
    import torch

    tc = cfg.get("training", {})
    base: dict[str, Any] = {
        "output_dir": str(output_dir),
        "num_train_epochs": float(tc.get("epochs", 1)),
        "learning_rate": float(tc.get("learning_rate", 5.0e-6)),
        "weight_decay": float(tc.get("weight_decay", 0.0)),
        "warmup_ratio": float(tc.get("warmup_ratio", 0.0)),
        "lr_scheduler_type": str(tc.get("lr_scheduler_type", "linear")),
        "per_device_train_batch_size": int(tc.get("per_device_train_batch_size", 1)),
        "gradient_accumulation_steps": int(tc.get("gradient_accumulation_steps", 8)),
        "max_grad_norm": float(tc.get("max_grad_norm", 1.0)),
        "optim": str(tc.get("optim", "adamw_torch")),
        "bf16": bool(tc.get("bf16", False)) and torch.cuda.is_available(),
        "fp16": bool(tc.get("fp16", False)) and torch.cuda.is_available(),
        "gradient_checkpointing": bool(tc.get("gradient_checkpointing", True)),
        "seed": int(tc.get("seed", 42)),
        "save_strategy": tc.get("save_strategy", "epoch"),
        "logging_steps": int(tc.get("logging_steps", 10)),
        "save_total_limit": int(tc.get("save_total_limit", 3)),
        "report_to": _normalize_report_to(tc.get("report_to")),
    }
    if "max_steps" in tc:
        base["max_steps"] = int(tc["max_steps"])
    return {k: v for k, v in base.items() if k in param_names}


def run_and_save(
    *,
    method: str,
    cfg: dict[str, Any],
    smoke_test: bool,
    output_dir: Path,
    tokenizer: Any,
    base_model: str,
    peft_method: str,
    make_trainer: Callable[[list[Any], str], Any],
) -> Path:
    """Wire the tracker + metrics callback, build the trainer, train, and save.

    `make_trainer(callbacks, tok_kwarg)` returns the constructed TRL trainer.
    `tok_kwarg` is 'processing_class' or 'tokenizer' depending on TRL version.
    """
    tracker_cfg = cfg.get("tracking", {})
    tracker = get_tracker(tracker_cfg.get("backend"))
    if tracker_cfg.get("experiment_name"):
        tracker.set_experiment(tracker_cfg["experiment_name"])

    run_name = cfg.get("run_name", f"puffin-{method}")
    config_h = config_hash(cfg)
    identity = run_identity()

    with tracker.start_run(run_name=run_name):
        tracker.log_params(flatten({**cfg, "_config_hash": config_h}))
        tracker.set_tags(
            {
                "method": method,
                "config_hash": config_h,
                "peft_method": peft_method,
                "git_sha": identity.get("git_sha") or "n/a",
                "platform": identity.get("platform"),
            }
        )

        metrics_cb = TrainingMetricsCallback(
            output_dir=output_dir,
            method=method,
            run_name=run_name,
            smoke_test=smoke_test,
            base_model=base_model,
            peft_method=peft_method,
        )

        # transformers >=4.46 renamed the tokenizer kwarg to processing_class.
        from transformers import Trainer

        tok_kwarg = (
            "processing_class"
            if "processing_class" in inspect.signature(Trainer.__init__).parameters
            else "tokenizer"
        )
        trainer = make_trainer([metrics_cb], tok_kwarg)
        try:
            trainer.train()
        except BaseException as exc:
            metrics_cb.mark_failed(f"{type(exc).__name__}: {exc}", state=trainer.state)
            raise
        trainer.save_model(str(output_dir))
        with contextlib.suppress(Exception):
            tokenizer.save_pretrained(str(output_dir))

        (output_dir / "lineage.json").write_text(
            json.dumps(
                {
                    "method": method,
                    "config_hash": config_h,
                    "base_model": base_model,
                    "peft_method": peft_method,
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
            metrics = {k: float(v) for k, v in history[-1].items() if isinstance(v, (int, float))}
            if metrics:
                tracker.log_metrics(metrics)
        tracker.log_artifacts(str(output_dir))

    log.info("%s training complete; saved to %s", method.upper(), output_dir)
    return output_dir


def default_reward_funcs(cfg: dict[str, Any]) -> list[Callable[..., list[float]]]:
    """A built-in reward for GRPO/RLOO so they run without a separate reward
    model. Rewards a sensible, non-empty, non-degenerate answer length; if the
    config lists reward.keywords, also rewards containing them. Point at a real
    reward model or swap this out for a serious run."""
    rcfg = cfg.get("reward", {}) if isinstance(cfg.get("reward"), dict) else {}
    target = int(rcfg.get("target_chars", 200))
    keywords = [str(k).lower() for k in (rcfg.get("keywords") or [])]

    def reward(completions: list[Any], **_: Any) -> list[float]:
        out = []
        for c in completions:
            text = c if isinstance(c, str) else str(c)
            n = len(text.strip())
            # Triangular reward peaking at `target` chars, in [0, 1].
            length_score = max(0.0, 1.0 - abs(n - target) / max(target, 1))
            kw = 0.0
            if keywords:
                low = text.lower()
                kw = sum(1.0 for k in keywords if k in low) / len(keywords)
            out.append(0.7 * length_score + 0.3 * kw)
        return out

    reward.__name__ = "puffin_builtin_reward"
    return [reward]
