"""GRPO training (Group Relative Policy Optimization).

Online RL: for each prompt the model samples a group of completions, scores
them with a reward function, and pushes toward the better ones (no separate
value model, no paired data -- just prompts + a reward). Wraps TRL's
GRPOTrainer. A built-in length/keyword reward runs out of the box; point
`reward` in the config at something real for a serious run.

    python -m llmops.training.train_grpo --config configs/train_grpo.yaml
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
from llmops.features.chat_template import DEFAULT_CHAT_TEMPLATE_VERSION, get_chat_template
from llmops.training._trl_shared import (
    apply_smoke, common_config_kwargs, default_reward_funcs, run_and_save,
)
from llmops.training.train_sft_lora import (
    _build_peft_config, _load_model_and_tokenizer, _print_effective_config,
    _validate_config, _wrap_with_peft,
)

log = get_logger(__name__)


def _smoke_overrides(cfg: dict[str, Any]) -> dict[str, Any]:
    # num_generations must divide the effective batch; 2 x 2 works on CPU.
    cfg = apply_smoke(cfg, "artifacts/grpo-smoke",
                      extra_training={"per_device_train_batch_size": 2,
                                      "gradient_accumulation_steps": 1})
    g = cfg.setdefault("grpo", {})
    g["num_generations"] = 2
    g["max_completion_length"] = 16  # keep CPU generation fast in smoke
    return cfg


def _load_prompt_dataset(path: str | Path, *, limit: int | None = None) -> Any:
    """Rows: {prompt}. Extra fields are ignored."""
    from datasets import Dataset

    rows = []
    for r in read_jsonl(path):
        if "prompt" in r:
            rows.append({"prompt": r["prompt"]})
        elif "messages" in r and isinstance(r["messages"], list):
            rows.append({"prompt": r["messages"]})
    if limit is not None:
        rows = rows[:limit]
    if not rows:
        raise ValueError(f"No prompts in {path}. Each row needs a 'prompt'.")
    return Dataset.from_list(rows)


def _build_grpo_args(cfg: dict[str, Any], output_dir: Path) -> Any:
    from trl import GRPOConfig

    params = inspect.signature(GRPOConfig.__init__).parameters
    kwargs = common_config_kwargs(cfg, output_dir, params)
    data_cfg = cfg.get("data", {})
    g = cfg.get("grpo", {})
    for key, val in {
        "num_generations": int(g.get("num_generations", 4)),
        "max_completion_length": int(g.get("max_completion_length", 128)),
        "max_prompt_length": int(data_cfg.get("max_prompt_length", 256)),
        "temperature": float(g.get("temperature", 0.9)),
        "beta": float(g.get("beta", 0.04)),
    }.items():
        if key in params:
            kwargs[key] = val
    return GRPOConfig(**kwargs)


def train(cfg: dict[str, Any], *, smoke_test: bool = False) -> Path:
    if smoke_test:
        cfg = _smoke_overrides(dict(cfg))
    _validate_config(cfg)
    _print_effective_config(cfg)

    from trl import GRPOTrainer

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

    output_dir = Path(output_cfg.get("adapter_dir", "artifacts/grpo-adapter"))
    output_dir.mkdir(parents=True, exist_ok=True)
    args = _build_grpo_args(cfg, output_dir)
    reward_funcs = default_reward_funcs(cfg)
    peft_method = (lora_cfg.get("method") or "lora") if lora_cfg.get("enabled", True) else "full"

    def make_trainer(callbacks: list[Any], tok_kwarg: str) -> Any:
        return GRPOTrainer(
            model=model, reward_funcs=reward_funcs, args=args,
            train_dataset=train_ds, peft_config=trainer_peft,
            callbacks=callbacks, **{tok_kwarg: tokenizer})

    return run_and_save(
        method="grpo", cfg=cfg, smoke_test=smoke_test, output_dir=output_dir,
        tokenizer=tokenizer, base_model=model_cfg["base_model"],
        peft_method=peft_method, make_trainer=make_trainer)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GRPO training.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args(argv)
    train(load_yaml(args.config), smoke_test=args.smoke_test)
    return 0


if __name__ == "__main__":
    sys.exit(main())
