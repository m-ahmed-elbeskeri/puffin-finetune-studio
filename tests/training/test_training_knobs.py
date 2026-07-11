"""Tests for the HF / TRL / PEFT knob plumbing in train_sft_lora.

These tests do *not* run any real training. They exercise the small builder
helpers that translate the YAML schema into HF objects.
"""
from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")
trl = pytest.importorskip("trl")
peft = pytest.importorskip("peft")
transformers = pytest.importorskip("transformers")

from llmops.training.train_sft_lora import (  # noqa: E402
    _build_model_init_kwargs,
    _build_peft_config,
    _build_quantization_config,
    _normalize_report_to,
    _resolve_dtype,
)


# ---------------------------------------------------------------------------
# Quantization
# ---------------------------------------------------------------------------
def test_quantization_config_none_when_no_quant():
    assert _build_quantization_config(None) is None
    assert _build_quantization_config({}) is None


def test_quantization_config_bnb_4bit():
    from transformers import BitsAndBytesConfig

    cfg = {
        "backend": "bitsandbytes",
        "load_in_4bit": True,
        "bnb_4bit_quant_type": "nf4",
        "bnb_4bit_compute_dtype": "bfloat16",
        "bnb_4bit_use_double_quant": True,
    }
    qc = _build_quantization_config(cfg)
    assert isinstance(qc, BitsAndBytesConfig)
    assert qc.load_in_4bit is True
    assert qc.bnb_4bit_quant_type == "nf4"
    assert qc.bnb_4bit_compute_dtype == torch.bfloat16
    assert qc.bnb_4bit_use_double_quant is True


def test_quantization_config_bnb_8bit():
    from transformers import BitsAndBytesConfig

    qc = _build_quantization_config({"backend": "bitsandbytes", "load_in_8bit": True})
    assert isinstance(qc, BitsAndBytesConfig)
    assert qc.load_in_8bit is True


def test_quantization_config_rejects_gptq():
    with pytest.raises(ValueError, match="bitsandbytes"):
        _build_quantization_config({"backend": "gptq", "bits": 4})


def test_quantization_config_rejects_awq():
    with pytest.raises(ValueError, match="bitsandbytes"):
        _build_quantization_config({"backend": "awq"})


# ---------------------------------------------------------------------------
# Model init kwargs
# ---------------------------------------------------------------------------
def test_model_init_kwargs_default():
    kwargs = _build_model_init_kwargs(
        {"base_model": "x", "attn_impl": "sdpa"},
        {"bf16": False, "fp16": False},
    )
    assert kwargs["attn_implementation"] == "sdpa"
    assert kwargs["trust_remote_code"] is False
    assert kwargs["revision"] == "main"
    # dtype-keyword name varies across transformers versions; just check one is set
    assert "dtype" in kwargs or "torch_dtype" in kwargs


def test_model_init_kwargs_flash_attention():
    kwargs = _build_model_init_kwargs(
        {"base_model": "x", "attn_impl": "flash_attention_2"},
        {"bf16": True, "fp16": False},
    )
    assert kwargs["attn_implementation"] == "flash_attention_2"


def test_model_init_kwargs_rejects_unknown_attn():
    with pytest.raises(ValueError, match="attn_impl"):
        _build_model_init_kwargs({"attn_impl": "bogus"}, {})


def test_model_init_kwargs_attaches_quantization():
    cfg = {
        "base_model": "x",
        "attn_impl": "sdpa",
        "quantization": {"backend": "bitsandbytes", "load_in_4bit": True},
    }
    kwargs = _build_model_init_kwargs(cfg, {"bf16": False, "fp16": False})
    assert "quantization_config" in kwargs


def test_resolve_dtype_no_cuda_returns_auto():
    # On a CPU-only box, bf16/fp16 must NOT force a dtype (would crash CPU training).
    if torch.cuda.is_available():
        pytest.skip("only meaningful on CPU")
    assert _resolve_dtype({"bf16": True}) == "auto"
    assert _resolve_dtype({"fp16": True}) == "auto"


# ---------------------------------------------------------------------------
# PEFT config builder
# ---------------------------------------------------------------------------
def test_peft_config_disabled():
    assert _build_peft_config({"enabled": False}) is None
    assert _build_peft_config({"enabled": True, "method": "none"}) is None


def test_peft_config_lora_defaults():
    from peft import LoraConfig

    pc = _build_peft_config({"enabled": True, "method": "lora", "r": 8, "alpha": 16})
    assert isinstance(pc, LoraConfig)
    assert pc.r == 8
    assert pc.lora_alpha == 16
    assert pc.task_type == "CAUSAL_LM"
    assert pc.use_dora is False


def test_peft_config_dora_method_shorthand():
    from peft import LoraConfig

    pc = _build_peft_config({"enabled": True, "method": "dora", "r": 16})
    assert isinstance(pc, LoraConfig)
    assert pc.use_dora is True


def test_peft_config_dora_via_flag():
    pc = _build_peft_config({"enabled": True, "method": "lora", "use_dora": True})
    assert pc.use_dora is True


def test_peft_config_rslora():
    pc = _build_peft_config(
        {"enabled": True, "method": "lora", "use_rslora": True, "r": 32}
    )
    assert pc.use_rslora is True


def test_peft_config_ia3():
    from peft import IA3Config

    pc = _build_peft_config({"enabled": True, "method": "ia3"})
    assert isinstance(pc, IA3Config)
    assert pc.task_type == "CAUSAL_LM"


def test_peft_config_prompt_tuning():
    from peft import PromptTuningConfig

    pc = _build_peft_config(
        {"enabled": True, "method": "prompt_tuning", "num_virtual_tokens": 30}
    )
    assert isinstance(pc, PromptTuningConfig)
    assert pc.num_virtual_tokens == 30


def test_peft_config_prefix_tuning():
    from peft import PrefixTuningConfig

    pc = _build_peft_config(
        {"enabled": True, "method": "prefix_tuning", "num_virtual_tokens": 16}
    )
    assert isinstance(pc, PrefixTuningConfig)


def test_peft_config_p_tuning():
    from peft import PromptEncoderConfig

    pc = _build_peft_config({"enabled": True, "method": "p_tuning"})
    assert isinstance(pc, PromptEncoderConfig)


def test_peft_config_adalora():
    from peft import AdaLoraConfig

    pc = _build_peft_config(
        {
            "enabled": True,
            "method": "adalora",
            "r": 8,
            "adalora": {"target_r": 4, "init_r": 12},
        }
    )
    assert isinstance(pc, AdaLoraConfig)
    assert pc.target_r == 4
    assert pc.init_r == 12


def test_peft_config_unknown_method():
    with pytest.raises(ValueError, match=r"lora\.method"):
        _build_peft_config({"enabled": True, "method": "made-up-method"})


# ---------------------------------------------------------------------------
# report_to normalization
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "value,expected",
    [
        (None, "none"),
        ([], "none"),
        ("none", "none"),
        ("wandb", "wandb"),
        ("mlflow", "mlflow"),
        (["wandb", "mlflow"], ["wandb", "mlflow"]),
        (["tensorboard"], ["tensorboard"]),
    ],
)
def test_normalize_report_to(value, expected):
    assert _normalize_report_to(value) == expected


# ---------------------------------------------------------------------------
# Loader engine guardrails
# ---------------------------------------------------------------------------
def test_unsloth_loader_requires_cuda():
    """unsloth without CUDA must fail fast with a clear message, not at runtime."""
    if torch.cuda.is_available():
        pytest.skip("only meaningful on CPU")
    from llmops.training.train_sft_lora import _load_model_and_tokenizer

    with pytest.raises(RuntimeError, match="CUDA"):
        _load_model_and_tokenizer(
            {"base_model": "x", "loader": "unsloth", "attn_impl": "sdpa"},
            {"bf16": False, "fp16": False},
        )


def test_unknown_loader_rejected():
    from llmops.training.train_sft_lora import _load_model_and_tokenizer

    with pytest.raises(ValueError, match="loader"):
        _load_model_and_tokenizer(
            {"base_model": "x", "loader": "bogus", "attn_impl": "sdpa"},
            {"bf16": False, "fp16": False},
        )
