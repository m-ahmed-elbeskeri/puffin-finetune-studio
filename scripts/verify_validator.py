"""Verify that the previously-failing CUDA combos now raise ConfigValidationError
BEFORE model load (instead of cryptic runtime errors deep inside TRL/torch).

Run with: PYTHONUTF8=1 .venv/Scripts/python scripts/verify_validator.py
"""
from __future__ import annotations

import os
import sys
import time
import traceback
from pathlib import Path

os.environ.setdefault("PUFFIN_TRACKING_BACKEND", "none")
os.environ.setdefault("PYTHONUTF8", "1")

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from llmops.common.config import load_yaml  # noqa: E402
from llmops.training.train_sft_lora import (  # noqa: E402
    ConfigValidationError,
    _validate_config,
)


def _check(name: str, cfg: dict, expect_match: str) -> bool:
    print(f"  [{name}]")
    t0 = time.perf_counter()
    try:
        _validate_config(cfg)
    except ConfigValidationError as e:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        msg = str(e)
        ok = expect_match.lower() in msg.lower()
        marker = "PASS" if ok else "FAIL"
        print(f"    {marker} in {elapsed_ms:.1f} ms — {msg[:160]}")
        if not ok:
            print(f"    !! expected '{expect_match}' in message")
        return ok
    except Exception as e:  # noqa: BLE001
        print(f"    FAIL: unexpected exception type {type(e).__name__}: {e}")
        traceback.print_exc()
        return False
    else:
        print(f"    FAIL: validator accepted bad config")
        return False


def main() -> int:
    base = load_yaml(REPO / "configs/train.yaml")

    results = []

    # Replicate the smoke-matrix fp4 failure:
    cfg = {**base}
    cfg["model"] = {
        **base["model"],
        "loader": "hf",
        "attn_impl": "eager",
        "quantization": {
            "backend": "bitsandbytes",
            "load_in_4bit": True,
            "bnb_4bit_quant_type": "fp4",
            "bnb_4bit_compute_dtype": "float16",
        },
    }
    cfg["training"] = {
        **base["training"],
        "bf16": True,    # wrong — compute_dtype says float16
        "fp16": False,
    }
    cfg["lora"] = {**base["lora"], "method": "lora", "r": 8, "alpha": 16}
    results.append(_check("qlora fp4 + bf16 (was: cryptic CUDA grad-scaler error)", cfg, "fp16=true"))

    # Replicate torch_compile failure on Windows (no triton)
    cfg = {**base}
    cfg["model"] = {**base["model"], "loader": "hf", "attn_impl": "eager", "quantization": None}
    cfg["training"] = {**base["training"], "torch_compile": True, "bf16": True}
    results.append(_check("torch_compile without triton (was: 114s TritonMissing crash)", cfg, "Triton"))

    # Bonus: bf16 + fp16 both set
    cfg = {**base}
    cfg["model"] = {**base["model"], "loader": "hf", "attn_impl": "eager", "quantization": None}
    cfg["training"] = {**base["training"], "bf16": True, "fp16": True}
    results.append(_check("bf16 + fp16 both set", cfg, "Pick exactly one"))

    # Bonus: flash_attention_2 without flash-attn
    cfg = {**base}
    cfg["model"] = {**base["model"], "attn_impl": "flash_attention_2", "quantization": None}
    cfg["training"] = {**base["training"], "bf16": True}
    results.append(_check("flash_attention_2 without flash-attn pkg", cfg, "flash-attn"))

    # Bonus: unknown loader
    cfg = {**base}
    cfg["model"] = {**base["model"], "loader": "made-up", "attn_impl": "eager", "quantization": None}
    cfg["training"] = {**base["training"], "bf16": True}
    results.append(_check("unknown loader name", cfg, "not supported"))

    passed = sum(results)
    total = len(results)
    print(f"\n{passed}/{total} passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
