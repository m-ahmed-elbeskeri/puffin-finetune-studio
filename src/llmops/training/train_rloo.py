"""RLOO training (REINFORCE Leave-One-Out).

Online RL like GRPO, but the baseline for each sampled completion is the mean
reward of the *other* samples in its group (leave-one-out) -- a lighter,
value-model-free PPO alternative. Wraps TRL's RLOOTrainer. Uses the same
prompt-only data + reward function as GRPO.

    python -m llmops.training.train_rloo --config configs/train_rloo.yaml
"""

from __future__ import annotations

import argparse
import inspect
import sys
from pathlib import Path
from typing import Any

from llmops.common.config import load_yaml
from llmops.common.logging import get_logger
from llmops.features.chat_template import DEFAULT_CHAT_TEMPLATE_VERSION, get_chat_template
from llmops.training._trl_shared import (
    apply_smoke,
    common_config_kwargs,
    default_reward_funcs,
    run_and_save,
)
from llmops.training.train_grpo import _load_prompt_dataset
from llmops.training.train_sft_lora import (
    _build_peft_config,
    _load_model_and_tokenizer,
    _print_effective_config,
    _validate_config,
    _wrap_with_peft,
)

log = get_logger(__name__)


def _smoke_overrides(cfg: dict[str, Any]) -> dict[str, Any]:
    cfg = apply_smoke(
        cfg,
        "artifacts/rloo-smoke",
        extra_training={"per_device_train_batch_size": 2, "gradient_accumulation_steps": 1},
    )
    r = cfg.setdefault("rloo", {})
    r["num_generations"] = 2
    r["max_completion_length"] = 16  # keep CPU generation fast in smoke
    return cfg


def _build_rloo_args(cfg: dict[str, Any], output_dir: Path) -> Any:
    from trl import RLOOConfig

    params = inspect.signature(RLOOConfig.__init__).parameters
    kwargs = common_config_kwargs(cfg, output_dir, params)
    data_cfg = cfg.get("data", {})
    r = cfg.get("rloo", {})
    for key, val in {
        "num_generations": int(r.get("num_generations", 4)),
        "max_completion_length": int(r.get("max_completion_length", 128)),
        "max_prompt_length": int(data_cfg.get("max_prompt_length", 256)),
        "temperature": float(r.get("temperature", 0.9)),
        "rloo_k": int(r.get("rloo_k", r.get("num_generations", 4))),
        "kl_coef": float(r.get("kl_coef", 0.05)),
    }.items():
        if key in params:
            kwargs[key] = val
    return RLOOConfig(**kwargs)


def train(cfg: dict[str, Any], *, smoke_test: bool = False) -> Path:
    if smoke_test:
        cfg = _smoke_overrides(dict(cfg))
    _validate_config(cfg)
    _print_effective_config(cfg)

    from trl import RLOOTrainer

    model_cfg = cfg["model"]
    train_cfg = cfg["training"]
    lora_cfg = cfg.get("lora", {})
    data_cfg = cfg["data"]
    output_cfg = cfg.get("output", {})
    tpl = data_cfg.get("chat_template_version", DEFAULT_CHAT_TEMPLATE_VERSION)

    model, tokenizer = _load_model_and_tokenizer(model_cfg, train_cfg)
    tokenizer.chat_template = get_chat_template(tpl)

    loader = (model_cfg.get("loader") or "hf").lower()
    peft_config = _build_peft_config(lora_cfg)
    if loader == "unsloth" and peft_config is not None:
        model = _wrap_with_peft(model, peft_config, lora_cfg, loader)
        trainer_peft = None
    else:
        trainer_peft = peft_config

    train_ds = _load_prompt_dataset(data_cfg["train_path"], limit=data_cfg.get("limit"))

    output_dir = Path(output_cfg.get("adapter_dir", "artifacts/rloo-adapter"))
    output_dir.mkdir(parents=True, exist_ok=True)
    args = _build_rloo_args(cfg, output_dir)
    reward_funcs = default_reward_funcs(cfg)
    peft_method = (lora_cfg.get("method") or "lora") if lora_cfg.get("enabled", True) else "full"

    def make_trainer(callbacks: list[Any], tok_kwarg: str) -> Any:
        return RLOOTrainer(
            model=model,
            reward_funcs=reward_funcs,
            args=args,
            train_dataset=train_ds,
            peft_config=trainer_peft,
            callbacks=callbacks,
            **{tok_kwarg: tokenizer},
        )

    return run_and_save(
        method="rloo",
        cfg=cfg,
        smoke_test=smoke_test,
        output_dir=output_dir,
        tokenizer=tokenizer,
        base_model=model_cfg["base_model"],
        peft_method=peft_method,
        make_trainer=make_trainer,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RLOO training.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args(argv)
    train(load_yaml(args.config), smoke_test=args.smoke_test)
    return 0


if __name__ == "__main__":
    sys.exit(main())
