"""Tests for the fail-fast config validator. These run on CPU only.

The validator is deliberately strict: it raises ConfigValidationError with an
actionable fix BEFORE any model load. We assert both that it fires on bad
configs and that it stays silent on good ones.
"""
from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")
trl = pytest.importorskip("trl")
peft = pytest.importorskip("peft")
transformers = pytest.importorskip("transformers")

from llmops.training.train_sft_lora import (  # noqa: E402
    ConfigValidationError,
    _validate_config,
)

CUDA = torch.cuda.is_available()


def _base_cfg(**training_override):
    """A minimal cfg that passes validation on CPU (everything off)."""
    cfg = {
        "model": {
            "base_model": "x",
            "loader": "hf",
            "attn_impl": "eager",
            "quantization": None,
        },
        "training": {
            "bf16": False,
            "fp16": False,
            "torch_compile": False,
            "use_liger_kernel": False,
        },
        "lora": {"enabled": True, "method": "lora"},
        "data": {"max_seq_length": 512},
    }
    cfg["training"].update(training_override)
    return cfg


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------
def test_cpu_eager_no_quant_passes():
    _validate_config(_base_cfg())  # no raise


def test_sdpa_passes_on_cpu_too():
    cfg = _base_cfg()
    cfg["model"]["attn_impl"] = "sdpa"
    _validate_config(cfg)


def test_loader_hf_explicit_passes():
    cfg = _base_cfg()
    cfg["model"]["loader"] = "hf"
    _validate_config(cfg)


# ---------------------------------------------------------------------------
# Mixed precision rules
# ---------------------------------------------------------------------------
def test_both_bf16_and_fp16_rejected():
    cfg = _base_cfg(bf16=True, fp16=True)
    with pytest.raises(ConfigValidationError, match="both true"):
        _validate_config(cfg)


def test_bf16_without_cuda_rejected():
    if CUDA:
        pytest.skip("only meaningful on CPU")
    cfg = _base_cfg(bf16=True)
    with pytest.raises(ConfigValidationError, match="CUDA"):
        _validate_config(cfg)


def test_fp16_without_cuda_rejected():
    if CUDA:
        pytest.skip("only meaningful on CPU")
    cfg = _base_cfg(fp16=True)
    with pytest.raises(ConfigValidationError, match="CUDA"):
        _validate_config(cfg)


# ---------------------------------------------------------------------------
# Quantization rules
# ---------------------------------------------------------------------------
def test_quant_without_cuda_rejected():
    if CUDA:
        pytest.skip("only meaningful on CPU")
    cfg = _base_cfg()
    cfg["model"]["quantization"] = {"backend": "bitsandbytes", "load_in_4bit": True}
    with pytest.raises(ConfigValidationError, match="CUDA"):
        _validate_config(cfg)


def test_qlora_dtype_mismatch_bf16_required_rejected():
    """bnb_4bit_compute_dtype=bfloat16 + fp16=true is the combo that broke in the smoke matrix."""
    if not CUDA:
        pytest.skip("CUDA required to even reach the dtype-alignment check")
    cfg = _base_cfg(fp16=True, bf16=False)
    cfg["model"]["quantization"] = {
        "backend": "bitsandbytes",
        "load_in_4bit": True,
        "bnb_4bit_compute_dtype": "bfloat16",
    }
    with pytest.raises(ConfigValidationError, match="bf16=true"):
        _validate_config(cfg)


def test_qlora_dtype_mismatch_fp16_required_rejected():
    """bnb_4bit_compute_dtype=float16 + bf16=true (what bit us in the smoke matrix)."""
    if not CUDA:
        pytest.skip("CUDA required")
    cfg = _base_cfg(bf16=True, fp16=False)
    cfg["model"]["quantization"] = {
        "backend": "bitsandbytes",
        "load_in_4bit": True,
        "bnb_4bit_compute_dtype": "float16",
    }
    with pytest.raises(ConfigValidationError, match="fp16=true"):
        _validate_config(cfg)


def test_qlora_bad_compute_dtype_rejected():
    if not CUDA:
        pytest.skip("CUDA required")
    cfg = _base_cfg(bf16=True)
    cfg["model"]["quantization"] = {
        "backend": "bitsandbytes",
        "load_in_4bit": True,
        "bnb_4bit_compute_dtype": "float64",  # invalid
    }
    with pytest.raises(ConfigValidationError, match="not supported"):
        _validate_config(cfg)


def test_qlora_with_lora_disabled_rejected():
    """4-bit weights can't be trained without an adapter — must be QLoRA, not bare 4-bit FT."""
    if not CUDA:
        pytest.skip("CUDA required")
    cfg = _base_cfg(bf16=True)
    cfg["model"]["quantization"] = {
        "backend": "bitsandbytes",
        "load_in_4bit": True,
        "bnb_4bit_compute_dtype": "bfloat16",
    }
    cfg["lora"]["enabled"] = False
    with pytest.raises(ConfigValidationError, match="QLoRA"):
        _validate_config(cfg)


# ---------------------------------------------------------------------------
# Attention impls
# ---------------------------------------------------------------------------
def test_flash_attention_2_without_package_rejected():
    cfg = _base_cfg()
    cfg["model"]["attn_impl"] = "flash_attention_2"
    try:
        import flash_attn  # noqa: F401
        pytest.skip("flash-attn is installed; this test asserts the missing-package error")
    except ImportError:
        pass
    with pytest.raises(ConfigValidationError, match="flash-attn"):
        _validate_config(cfg)


# ---------------------------------------------------------------------------
# torch_compile / Liger guardrails
# ---------------------------------------------------------------------------
def test_torch_compile_without_triton_rejected():
    cfg = _base_cfg(torch_compile=True)
    try:
        import triton  # noqa: F401
        pytest.skip("triton is installed; this test asserts the missing-package error")
    except ImportError:
        pass
    with pytest.raises(ConfigValidationError, match="Triton"):
        _validate_config(cfg)


def test_use_liger_kernel_without_package_rejected():
    cfg = _base_cfg(use_liger_kernel=True)
    try:
        import liger_kernel  # noqa: F401
        pytest.skip("liger-kernel is installed")
    except ImportError:
        pass
    with pytest.raises(ConfigValidationError, match="liger-kernel"):
        _validate_config(cfg)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------
def test_unsloth_without_cuda_rejected():
    if CUDA:
        pytest.skip("only meaningful on CPU")
    cfg = _base_cfg()
    cfg["model"]["loader"] = "unsloth"
    with pytest.raises(ConfigValidationError, match="CUDA"):
        _validate_config(cfg)


def test_unknown_loader_rejected():
    cfg = _base_cfg()
    cfg["model"]["loader"] = "made-up-engine"
    with pytest.raises(ConfigValidationError, match="not supported"):
        _validate_config(cfg)


# ---------------------------------------------------------------------------
# Error messages must include the fix
# ---------------------------------------------------------------------------
def test_error_message_includes_actionable_fix():
    """Every validator error should tell the user what to set instead."""
    cfg = _base_cfg(bf16=True, fp16=True)
    with pytest.raises(ConfigValidationError) as ei:
        _validate_config(cfg)
    msg = str(ei.value)
    # Mentions both alternatives so the user can choose.
    assert "Pick exactly one" in msg
    assert "bf16" in msg
    assert "fp16" in msg
