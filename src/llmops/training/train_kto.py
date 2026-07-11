"""KTO training (Kahneman-Tversky Optimization).

Aligns a model from *unpaired* feedback: each row is a prompt + a single
completion + a boolean label (True = desirable / thumbs-up, False = not).
Cheaper to collect than DPO pairs. Wraps TRL's KTOTrainer.

    python -m llmops.training.train_kto --config configs/train_kto.yaml
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
    apply_smoke,
    common_config_kwargs,
    run_and_save,
)
from llmops.training.train_sft_lora import (
    _build_peft_config,
    _load_model_and_tokenizer,
    _print_effective_config,
    _validate_config,
    _wrap_with_peft,
)

log = get_logger(__name__)


def _smoke_overrides(cfg: dict[str, Any]) -> dict[str, Any]:
    # KTO's KL term requires an actual batch size > 1.
    return apply_smoke(
        cfg, "artifacts/kto-smoke", extra_training={"per_device_train_batch_size": 2}
    )


def _load_kto_dataset(path: str | Path, *, limit: int | None = None) -> Any:
    """Rows: {prompt, completion, label(bool)}."""
    from datasets import Dataset

    rows = []
    for r in read_jsonl(path):
        if "prompt" not in r or "completion" not in r or "label" not in r:
            continue
        rows.append(
            {"prompt": r["prompt"], "completion": r["completion"], "label": bool(r["label"])}
        )
    if limit is not None:
        rows = rows[:limit]
    if not rows:
        raise ValueError(
            f"No valid KTO rows in {path}. Each row needs prompt, completion, and a boolean label."
        )
    return Dataset.from_list(rows)


def _build_kto_args(cfg: dict[str, Any], output_dir: Path) -> Any:
    from trl import KTOConfig

    params = inspect.signature(KTOConfig.__init__).parameters
    kwargs = common_config_kwargs(cfg, output_dir, params)
    data_cfg = cfg.get("data", {})
    kto_cfg = cfg.get("kto", {})
    for key, val in {
        "beta": float(kto_cfg.get("beta", 0.1)),
        "desirable_weight": float(kto_cfg.get("desirable_weight", 1.0)),
        "undesirable_weight": float(kto_cfg.get("undesirable_weight", 1.0)),
        "max_length": int(data_cfg.get("max_length", 1024)),
        "max_prompt_length": int(data_cfg.get("max_prompt_length", 512)),
    }.items():
        if key in params:
            kwargs[key] = val
    return KTOConfig(**kwargs)


def train(cfg: dict[str, Any], *, smoke_test: bool = False) -> Path:
    if smoke_test:
        cfg = _smoke_overrides(dict(cfg))
    _validate_config(cfg)
    _print_effective_config(cfg)

    from trl import KTOTrainer

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

    train_ds = _load_kto_dataset(data_cfg["train_path"], limit=data_cfg.get("limit"))
    eval_ds = (
        _load_kto_dataset(data_cfg["eval_path"], limit=data_cfg.get("limit"))
        if data_cfg.get("eval_path")
        else None
    )

    output_dir = Path(output_cfg.get("adapter_dir", "artifacts/kto-adapter"))
    output_dir.mkdir(parents=True, exist_ok=True)
    args = _build_kto_args(cfg, output_dir)
    peft_method = (lora_cfg.get("method") or "lora") if lora_cfg.get("enabled", True) else "full"

    def make_trainer(callbacks: list[Any], tok_kwarg: str) -> Any:
        return KTOTrainer(
            model=model,
            args=args,
            train_dataset=train_ds,
            eval_dataset=eval_ds,
            peft_config=trainer_peft,
            callbacks=callbacks,
            **{tok_kwarg: tokenizer},
        )

    return run_and_save(
        method="kto",
        cfg=cfg,
        smoke_test=smoke_test,
        output_dir=output_dir,
        tokenizer=tokenizer,
        base_model=model_cfg["base_model"],
        peft_method=peft_method,
        make_trainer=make_trainer,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="KTO training.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args(argv)
    train(load_yaml(args.config), smoke_test=args.smoke_test)
    return 0


if __name__ == "__main__":
    sys.exit(main())
