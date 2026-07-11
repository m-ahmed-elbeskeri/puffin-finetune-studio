"""Tests for the Neuron-specific validator rules.

These run on CPU and assert the validator rejects Neuron-incompatible combos.
"""

from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")
trl = pytest.importorskip("trl")
peft = pytest.importorskip("peft")
transformers = pytest.importorskip("transformers")

from llmops.training.train_sft_lora import ConfigValidationError, _validate_config  # noqa: E402


def _neuron_cfg(**overrides):
    """A baseline neuron cfg. Caller overrides specific keys."""
    cfg = {
        "model": {
            "base_model": "x",
            "loader": "neuron",
            "attn_impl": "eager",
            "quantization": None,
        },
        "training": {
            "bf16": True,
            "fp16": False,
            "torch_compile": False,
            "use_liger_kernel": False,
            "optim": "adamw_torch",
        },
        "lora": {"enabled": True, "method": "lora"},
        "data": {"max_seq_length": 512},
    }
    for k, v in overrides.items():
        if k in cfg and isinstance(cfg[k], dict) and isinstance(v, dict):
            cfg[k].update(v)
        else:
            cfg[k] = v
    return cfg


def test_neuron_without_optimum_neuron_rejected():
    """If optimum-neuron isn't installed, validator must reject — not crash at runtime."""
    try:
        import optimum.neuron  # noqa: F401

        pytest.skip("optimum-neuron is installed; can't test missing-package error")
    except ImportError:
        pass
    with pytest.raises(ConfigValidationError, match="optimum-neuron"):
        _validate_config(_neuron_cfg())


def test_neuron_plus_quantization_rejected():
    cfg = _neuron_cfg()
    cfg["model"]["quantization"] = {"backend": "bitsandbytes", "load_in_4bit": True}
    with pytest.raises(ConfigValidationError, match="Trainium does NOT support bitsandbytes"):
        _validate_config(cfg)


def test_neuron_plus_flash_attention_2_rejected():
    cfg = _neuron_cfg()
    cfg["model"]["attn_impl"] = "flash_attention_2"
    with pytest.raises(ConfigValidationError, match="Trainium uses its own attention"):
        _validate_config(cfg)


def test_neuron_plus_liger_rejected():
    cfg = _neuron_cfg()
    cfg["training"]["use_liger_kernel"] = True
    with pytest.raises(ConfigValidationError, match="Liger Triton kernels are CUDA-only"):
        _validate_config(cfg)


def test_neuron_plus_torch_compile_rejected():
    cfg = _neuron_cfg()
    cfg["training"]["torch_compile"] = True
    with pytest.raises(ConfigValidationError, match="NeuronTrainer handles its own"):
        _validate_config(cfg)


@pytest.mark.parametrize(
    "optim", ["paged_adamw_8bit", "paged_adamw_32bit", "lion_8bit", "adamw_8bit"]
)
def test_neuron_plus_bnb_optimizers_rejected(optim):
    cfg = _neuron_cfg()
    cfg["training"]["optim"] = optim
    with pytest.raises(ConfigValidationError, match="requires bitsandbytes"):
        _validate_config(cfg)


def test_neuron_neutral_optim_passes_if_pkg_installed():
    """When all the constraints align, validation passes (only if optimum-neuron is present)."""
    try:
        import optimum.neuron  # noqa: F401
    except ImportError:
        pytest.skip("optimum-neuron not installed on this box; can't test the happy path")
    _validate_config(_neuron_cfg())  # no raise expected


def test_neuron_error_messages_actionable():
    """Each Neuron-rejection should propose a concrete next step."""
    try:
        import optimum.neuron  # noqa: F401
    except ImportError:
        pytest.skip("env-dependent path")
    cfg = _neuron_cfg()
    cfg["model"]["attn_impl"] = "flash_attention_2"
    with pytest.raises(ConfigValidationError) as ei:
        _validate_config(cfg)
    msg = str(ei.value)
    # Should propose the fix
    assert "eager" in msg or "CUDA" in msg
