"""Reward-model training.

Trains a sequence-classification head on preference pairs so it scores an
answer's quality with a scalar -- the reward signal that RLOO/GRPO/PPO
optimize against. Data is the same {prompt, chosen, rejected} you'd use for
DPO. Wraps TRL's RewardTrainer.

    python -m llmops.training.train_reward --config configs/train_reward.yaml
"""
from __future__ import annotations

import argparse
import inspect
import sys
from pathlib import Path
from typing import Any

from llmops.common.config import load_yaml
from llmops.common.logging import get_logger
from llmops.data.io_utils import read_jsonl
from llmops.training._trl_shared import (
    apply_smoke, common_config_kwargs, run_and_save,
)
from llmops.training.train_sft_lora import (
    _build_model_init_kwargs, _build_peft_config, _print_effective_config,
    _validate_config,
)

log = get_logger(__name__)


def _smoke_overrides(cfg: dict[str, Any]) -> dict[str, Any]:
    return apply_smoke(cfg, "artifacts/reward-smoke")


def _load_reward_model_and_tokenizer(model_cfg: dict[str, Any], train_cfg: dict[str, Any]):
    """A reward model is a base LM with a scalar classification head."""
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    base_model = model_cfg["base_model"]
    tokenizer = AutoTokenizer.from_pretrained(
        base_model, use_fast=True,
        trust_remote_code=bool(model_cfg.get("trust_remote_code", False)))
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    init_kwargs = _build_model_init_kwargs(model_cfg, train_cfg)
    model = AutoModelForSequenceClassification.from_pretrained(
        base_model, num_labels=1, **init_kwargs)
    if model.config.pad_token_id is None:
        model.config.pad_token_id = tokenizer.pad_token_id
    return model, tokenizer


def _load_pref_dataset(path: str | Path, *, limit: int | None = None) -> Any:
    """Rows: {chosen, rejected} (a prompt field is folded in if present)."""
    from datasets import Dataset

    rows = []
    for r in read_jsonl(path):
        if "chosen" not in r or "rejected" not in r:
            continue
        prompt = r.get("prompt")
        chosen, rejected = r["chosen"], r["rejected"]
        if prompt and isinstance(chosen, str) and isinstance(rejected, str):
            chosen = f"{prompt}\n{chosen}"
            rejected = f"{prompt}\n{rejected}"
        rows.append({"chosen": chosen, "rejected": rejected})
    if limit is not None:
        rows = rows[:limit]
    if not rows:
        raise ValueError(
            f"No preference pairs in {path}. Each row needs chosen + rejected.")
    return Dataset.from_list(rows)


def _build_reward_args(cfg: dict[str, Any], output_dir: Path) -> Any:
    from trl import RewardConfig

    params = inspect.signature(RewardConfig.__init__).parameters
    kwargs = common_config_kwargs(cfg, output_dir, params)
    data_cfg = cfg.get("data", {})
    if "max_length" in params:
        kwargs["max_length"] = int(data_cfg.get("max_length", 1024))
    return RewardConfig(**kwargs)


def train(cfg: dict[str, Any], *, smoke_test: bool = False) -> Path:
    if smoke_test:
        cfg = _smoke_overrides(dict(cfg))
    _validate_config(cfg)
    _print_effective_config(cfg)

    from trl import RewardTrainer

    model_cfg = cfg["model"]
    train_cfg = cfg["training"]
    lora_cfg = cfg.get("lora", {})
    data_cfg = cfg["data"]
    output_cfg = cfg.get("output", {})

    model, tokenizer = _load_reward_model_and_tokenizer(model_cfg, train_cfg)
    peft_config = _build_peft_config(lora_cfg)
    # A reward model is a classifier, not a generator: the LoRA adapter must
    # target the SEQ_CLS task or PEFT wires it as a causal LM and crashes.
    if peft_config is not None:
        from peft import TaskType
        peft_config.task_type = TaskType.SEQ_CLS

    train_ds = _load_pref_dataset(data_cfg["train_path"], limit=data_cfg.get("limit"))
    eval_ds = (_load_pref_dataset(data_cfg["eval_path"], limit=data_cfg.get("limit"))
               if data_cfg.get("eval_path") else None)

    output_dir = Path(output_cfg.get("adapter_dir", "artifacts/reward-model"))
    output_dir.mkdir(parents=True, exist_ok=True)
    args = _build_reward_args(cfg, output_dir)
    peft_method = (lora_cfg.get("method") or "lora") if lora_cfg.get("enabled", True) else "full"

    def make_trainer(callbacks: list[Any], tok_kwarg: str) -> Any:
        return RewardTrainer(
            model=model, args=args, train_dataset=train_ds, eval_dataset=eval_ds,
            peft_config=peft_config, callbacks=callbacks, **{tok_kwarg: tokenizer})

    return run_and_save(
        method="reward", cfg=cfg, smoke_test=smoke_test, output_dir=output_dir,
        tokenizer=tokenizer, base_model=model_cfg["base_model"],
        peft_method=peft_method, make_trainer=make_trainer)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reward-model training.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args(argv)
    train(load_yaml(args.config), smoke_test=args.smoke_test)
    return 0


if __name__ == "__main__":
    sys.exit(main())
