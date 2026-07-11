"""Driver that smoke-trains SmolLM2-135M with every method/knob combination
the puffin config exposes, then prints a pass/fail matrix.

Intended for ad-hoc verification on Windows+CPU — does NOT need CUDA, bnb,
unsloth, flash-attn, or any other GPU-only dependency.

Usage:
    PYTHONUTF8=1 .venv/Scripts/python scripts/smoke_all_methods.py
"""
from __future__ import annotations

import copy
import gc
import os
import shutil
import sys
import time
import traceback
from pathlib import Path

os.environ.setdefault("PUFFIN_TRACKING_BACKEND", "none")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("PYTHONUTF8", "1")

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from llmops.common.config import load_yaml  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _deep_merge(a: dict, b: dict) -> dict:
    """Return a new dict where b's keys override a's, recursing into dicts."""
    out = copy.deepcopy(a)
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _run_sft(name: str, overrides: dict, post_smoke: dict | None = None) -> dict:
    """Smoke-train SFT with overrides on top of configs/train.yaml. Returns a result row.

    `overrides` are merged BEFORE smoke overrides run (so smoke can stomp them).
    `post_smoke` are merged AFTER smoke overrides — use this to keep CUDA-only
    knobs (quantization, bf16, fp16, use_liger_kernel, attn_impl, optim, torch_compile)
    that the default smoke flow disables for CPU safety.
    """
    import llmops.training.train_sft_lora as mod

    adapter_dir = REPO / f"artifacts/smoke-{name}"
    if adapter_dir.exists():
        shutil.rmtree(adapter_dir, ignore_errors=True)

    base = load_yaml(REPO / "configs/train.yaml")
    cfg = _deep_merge(base, overrides)
    cfg.setdefault("output", {})["adapter_dir"] = str(adapter_dir)

    orig_smoke = mod._smoke_overrides
    if post_smoke:
        def patched(c):
            return _deep_merge(orig_smoke(c), post_smoke)
        mod._smoke_overrides = patched

    t0 = time.perf_counter()
    try:
        out = mod.train(cfg, smoke_test=True)
        elapsed = time.perf_counter() - t0
        produced = out.exists() and any(out.iterdir())
        return {
            "name": name,
            "status": "PASS" if produced else "FAIL",
            "elapsed_s": round(elapsed, 1),
            "adapter_dir": str(out) if produced else "",
            "error": "",
        }
    except Exception as e:  # noqa: BLE001
        return {
            "name": name,
            "status": "FAIL",
            "elapsed_s": round(time.perf_counter() - t0, 1),
            "adapter_dir": "",
            "error": f"{type(e).__name__}: {e}",
        }
    finally:
        mod._smoke_overrides = orig_smoke
        gc.collect()


def _run_dpo(name: str, overrides: dict, post_smoke: dict | None = None) -> dict:
    import llmops.training.train_dpo as mod

    adapter_dir = REPO / f"artifacts/smoke-dpo-{name}"
    if adapter_dir.exists():
        shutil.rmtree(adapter_dir, ignore_errors=True)

    base = load_yaml(REPO / "configs/train_dpo.yaml")
    cfg = _deep_merge(base, overrides)
    cfg.setdefault("output", {})["adapter_dir"] = str(adapter_dir)

    orig_smoke = mod._smoke_overrides
    if post_smoke:
        def patched(c):
            return _deep_merge(orig_smoke(c), post_smoke)
        mod._smoke_overrides = patched

    t0 = time.perf_counter()
    try:
        out = mod.train(cfg, smoke_test=True)
        elapsed = time.perf_counter() - t0
        produced = out.exists() and any(out.iterdir())
        return {
            "name": name,
            "status": "PASS" if produced else "FAIL",
            "elapsed_s": round(elapsed, 1),
            "adapter_dir": str(out) if produced else "",
            "error": "",
        }
    except Exception as e:  # noqa: BLE001
        return {
            "name": name,
            "status": "FAIL",
            "elapsed_s": round(time.perf_counter() - t0, 1),
            "adapter_dir": "",
            "error": f"{type(e).__name__}: {e}",
        }
    finally:
        mod._smoke_overrides = orig_smoke
        gc.collect()


# ---------------------------------------------------------------------------
# Test matrix
# ---------------------------------------------------------------------------
SFT_PEFT_METHODS = [
    ("lora",           {"lora": {"method": "lora", "r": 4, "alpha": 8}}),
    ("dora",           {"lora": {"method": "dora", "r": 4, "alpha": 8}}),
    ("ia3",            {"lora": {"method": "ia3",
                                  "target_modules": ["k_proj", "v_proj", "down_proj"],
                                  "feedforward_modules": ["down_proj"]}}),
    ("adalora",        {"lora": {"method": "adalora", "r": 8, "alpha": 16,
                                  "adalora": {"target_r": 4, "init_r": 6,
                                              "tinit": 0, "tfinal": 0,
                                              "deltaT": 1, "total_step": 2}}}),
    ("prompt_tuning",  {"lora": {"method": "prompt_tuning", "num_virtual_tokens": 8}}),
    ("prefix_tuning",  {"lora": {"method": "prefix_tuning", "num_virtual_tokens": 8}}),
    ("p_tuning",       {"lora": {"method": "p_tuning",      "num_virtual_tokens": 8}}),
    ("full_ft",        {"lora": {"enabled": False, "method": "none"}}),
    ("rslora",         {"lora": {"method": "lora", "r": 64, "alpha": 16,
                                  "use_rslora": True}}),
    ("lora_pissa_init", {"lora": {"method": "lora", "r": 4, "alpha": 8,
                                   "init_lora_weights": "pissa"}}),
    ("all_linear_lora", {"lora": {"method": "lora", "r": 4, "alpha": 8,
                                   "target_modules": ["q_proj", "k_proj", "v_proj",
                                                      "o_proj", "gate_proj", "up_proj",
                                                      "down_proj"]}}),
]

SFT_LOSS_VARIANTS = [
    ("loss_nll",         {"training": {"loss_type": "nll"}}),
    ("loss_chunked_nll", {"training": {"loss_type": "chunked_nll"}}),
    ("loss_dft",         {"training": {"loss_type": "dft"}}),
    ("neftune_alpha_5",  {"training": {"neftune_noise_alpha": 5.0}}),
    ("completion_only",  {"training": {"completion_only_loss": True}}),
]

SFT_ATTN_IMPLS = [
    ("attn_eager", {"model": {"attn_impl": "eager"}}),
    ("attn_sdpa",  {"model": {"attn_impl": "sdpa"}}),
]

SFT_OPTIMIZERS = [
    ("optim_adamw_torch", {"training": {"optim": "adamw_torch"}}),
    ("optim_adafactor",   {"training": {"optim": "adafactor"}}),
]

DPO_LOSS_TYPES = [
    ("dpo_sigmoid",      {"dpo": {"loss_type": "sigmoid"}}),
    ("dpo_ipo",          {"dpo": {"loss_type": "ipo"}}),
    ("dpo_hinge",        {"dpo": {"loss_type": "hinge"}}),
    ("dpo_robust",       {"dpo": {"loss_type": "robust",
                                   "label_smoothing": 0.1}}),
    ("dpo_sigmoid_norm", {"dpo": {"loss_type": "sigmoid_norm"}}),
    ("dpo_apo_zero",     {"dpo": {"loss_type": "apo_zero"}}),
    ("dpo_bco_pair",     {"dpo": {"loss_type": "bco_pair"}}),
    ("dpo_nca_pair",     {"dpo": {"loss_type": "nca_pair"}}),
]

SKIPPED = [
    ("attn_flash_attention_2", "Requires building flash-attn from source on Windows (needs CUDA_HOME + MSVC)"),
    ("attn_flex_attention",    "Torch FlexAttention not stable on CUDA Windows in this torch build"),
    ("loader_unsloth",         "Requires Linux + NVIDIA CUDA"),
    ("use_liger_kernel",       "Requires triton, which has no Windows wheels"),
    ("parallelism_fsdp",       "Multi-GPU only (single GPU here)"),
    ("parallelism_deepspeed",  "Multi-GPU only (single GPU here)"),
    ("parallelism_ddp",        "Multi-GPU only (single GPU here)"),
]

# CUDA-only methods. `post_smoke` overrides the conservative defaults that
# `_smoke_overrides` would force off (quantization, bf16, attn_impl on cuda, optim).
CUDA_ONLY = [
    # QLoRA paths
    ("qlora_bnb_4bit_nf4",     {}, {
        "model": {"quantization": {"backend": "bitsandbytes", "load_in_4bit": True,
                                    "bnb_4bit_quant_type": "nf4",
                                    "bnb_4bit_compute_dtype": "bfloat16",
                                    "bnb_4bit_use_double_quant": True}},
        "training": {"bf16": True, "fp16": False},
    }),
    ("qlora_bnb_4bit_fp4",     {}, {
        "model": {"quantization": {"backend": "bitsandbytes", "load_in_4bit": True,
                                    "bnb_4bit_quant_type": "fp4",
                                    "bnb_4bit_compute_dtype": "float16"}},
        "training": {"fp16": True, "bf16": False},
    }),
    ("bnb_8bit",               {}, {
        "model": {"quantization": {"backend": "bitsandbytes", "load_in_8bit": True}},
        "training": {"bf16": True, "fp16": False},
    }),
    # Mixed precision
    ("bf16_training",          {}, {
        "training": {"bf16": True, "fp16": False},
    }),
    # Attention impls on CUDA
    ("cuda_attn_sdpa",         {}, {
        "model": {"attn_impl": "sdpa"},
        "training": {"bf16": True},
    }),
    # Optimizers that need bnb / CUDA
    ("optim_adamw_torch_fused", {}, {
        "training": {"optim": "adamw_torch_fused", "bf16": True},
    }),
    ("optim_paged_adamw_8bit",  {}, {
        "training": {"optim": "paged_adamw_8bit", "bf16": True},
    }),
    ("optim_paged_adamw_32bit", {}, {
        "training": {"optim": "paged_adamw_32bit", "bf16": True},
    }),
    ("optim_lion_8bit",         {}, {
        "training": {"optim": "lion_8bit", "bf16": True},
    }),
    # Compile (PyTorch 2.x)
    ("torch_compile",          {}, {
        "training": {"torch_compile": True, "bf16": True},
    }),
    # Full QLoRA combo: 4-bit + paged optim + bf16 + LoRA r=8
    ("qlora_full_combo",       {"lora": {"method": "lora", "r": 8, "alpha": 16}}, {
        "model": {"quantization": {"backend": "bitsandbytes", "load_in_4bit": True,
                                    "bnb_4bit_quant_type": "nf4",
                                    "bnb_4bit_compute_dtype": "bfloat16",
                                    "bnb_4bit_use_double_quant": True}},
        "training": {"optim": "paged_adamw_8bit", "bf16": True},
    }),
]

# DPO on CUDA with quantized base — the realistic prod path.
CUDA_DPO = [
    ("dpo_qlora_sigmoid",      {"dpo": {"loss_type": "sigmoid"}}, {
        "model": {"quantization": {"backend": "bitsandbytes", "load_in_4bit": True,
                                    "bnb_4bit_quant_type": "nf4",
                                    "bnb_4bit_compute_dtype": "bfloat16"}},
        "training": {"bf16": True, "optim": "paged_adamw_8bit"},
    }),
    ("dpo_qlora_ipo",          {"dpo": {"loss_type": "ipo"}}, {
        "model": {"quantization": {"backend": "bitsandbytes", "load_in_4bit": True,
                                    "bnb_4bit_quant_type": "nf4",
                                    "bnb_4bit_compute_dtype": "bfloat16"}},
        "training": {"bf16": True, "optim": "paged_adamw_8bit"},
    }),
]


def main(only: str | None = None) -> int:
    results: list[dict] = []
    # 2-tuple entries use no post_smoke; 3-tuple entries override smoke defaults.
    cpu_groups = [
        ("SFT — PEFT methods",        SFT_PEFT_METHODS, _run_sft),
        ("SFT — loss / regularizer",  SFT_LOSS_VARIANTS, _run_sft),
        ("SFT — attention impl",      SFT_ATTN_IMPLS, _run_sft),
        ("SFT — optimizer",           SFT_OPTIMIZERS, _run_sft),
        ("DPO — loss types",          DPO_LOSS_TYPES, _run_dpo),
    ]
    cuda_groups = [
        ("CUDA — SFT (quant/optim/precision/compile)", CUDA_ONLY, _run_sft),
        ("CUDA — DPO (QLoRA)",                          CUDA_DPO,  _run_dpo),
    ]
    if only == "cuda":
        groups = cuda_groups
    elif only == "cpu":
        groups = cpu_groups
    else:
        groups = cpu_groups + cuda_groups

    for title, matrix, runner in groups:
        print(f"\n{'='*72}\n  {title}\n{'='*72}")
        for entry in matrix:
            name = entry[0]
            overrides = entry[1]
            post_smoke = entry[2] if len(entry) > 2 else None
            print(f"  -> {name:30s}", flush=True, end="")
            r = runner(name, overrides, post_smoke)
            r["group"] = title
            results.append(r)
            tag = (
                f" {r['status']:6s} {r['elapsed_s']:>5}s"
                f"{('  ' + r['error']) if r['error'] else ''}"
            )
            print(tag)

    print("\n" + "=" * 72)
    print("  Summary matrix")
    print("=" * 72)
    by_group: dict[str, list[dict]] = {}
    for r in results:
        by_group.setdefault(r["group"], []).append(r)
    for group, rows in by_group.items():
        passes = sum(1 for r in rows if r["status"] == "PASS")
        total = len(rows)
        print(f"\n{group}  ({passes}/{total} passed)")
        for r in rows:
            mark = "OK " if r["status"] == "PASS" else "XX "
            line = f"  [{mark}] {r['name']:30s} {r['elapsed_s']:>5}s"
            if r["error"]:
                line += f"   {r['error'][:80]}"
            print(line)

    print(f"\n{'=' * 72}\n  Skipped (not testable on Windows+CPU)\n{'=' * 72}")
    for name, why in SKIPPED:
        print(f"  [-- ] {name:30s} {why}")

    failed = [r for r in results if r["status"] != "PASS"]
    print(f"\nTotal: {len(results)} run, {len(results) - len(failed)} passed, "
          f"{len(failed)} failed, {len(SKIPPED)} skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    only = None
    if "--only" in sys.argv:
        i = sys.argv.index("--only")
        only = sys.argv[i + 1] if i + 1 < len(sys.argv) else None
    try:
        sys.exit(main(only=only))
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
