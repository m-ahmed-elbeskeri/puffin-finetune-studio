"""Merge a LoRA adapter into a base model and save a single deployable artifact.

CLI:
    python -m llmops.training.merge_adapter \
        --base meta-llama/Llama-3.1-8B-Instruct \
        --adapter artifacts/adapter \
        --output artifacts/model
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from llmops.common.logging import get_logger

log = get_logger(__name__)


def merge(
    base_model: str,
    adapter_dir: str,
    output_dir: str,
    *,
    revision: str = "main",
    trust_remote_code: bool = False,
) -> Path:
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    log.info("loading base model %s", base_model)
    model = AutoModelForCausalLM.from_pretrained(
        base_model,
        revision=revision,
        torch_dtype=torch.bfloat16 if torch.cuda.is_available() else "auto",
        device_map="auto" if torch.cuda.is_available() else None,
        trust_remote_code=trust_remote_code,
    )
    log.info("loading adapter from %s", adapter_dir)
    model = PeftModel.from_pretrained(model, adapter_dir)

    log.info("merging adapter into base weights")
    merged = model.merge_and_unload()

    log.info("saving merged model to %s", out)
    merged.save_pretrained(out, safe_serialization=True)

    tokenizer = AutoTokenizer.from_pretrained(adapter_dir, use_fast=True)
    tokenizer.save_pretrained(out)
    log.info("merge complete")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Merge LoRA adapter into base model.")
    parser.add_argument("--base", required=True, help="HF base model id or local path")
    parser.add_argument("--adapter", required=True, help="LoRA adapter directory")
    parser.add_argument("--output", required=True, help="Where to write the merged model")
    parser.add_argument("--revision", default="main")
    parser.add_argument("--trust-remote-code", action="store_true")
    args = parser.parse_args(argv)

    merge(
        base_model=args.base,
        adapter_dir=args.adapter,
        output_dir=args.output,
        revision=args.revision,
        trust_remote_code=args.trust_remote_code,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
