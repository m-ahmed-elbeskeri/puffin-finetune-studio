"""Tests for the DPO-specific validator."""
from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")
trl = pytest.importorskip("trl")
peft = pytest.importorskip("peft")
transformers = pytest.importorskip("transformers")

from llmops.training.train_dpo import _validate_dpo_config  # noqa: E402
from llmops.training.train_sft_lora import ConfigValidationError  # noqa: E402


def _base_dpo_cfg(**dpo_override):
    cfg = {
        "model": {"base_model": "x", "loader": "hf", "attn_impl": "eager"},
        "training": {"bf16": False, "fp16": False, "use_liger_kernel": False},
        "lora": {"enabled": True, "method": "lora"},
        "data": {"max_length": 1024, "max_prompt_length": 512},
        "dpo": {"beta": 0.1, "loss_type": "sigmoid"},
    }
    cfg["dpo"].update(dpo_override)
    return cfg


def test_sigmoid_passes():
    _validate_dpo_config(_base_dpo_cfg())  # no raise


def test_exo_pair_requires_label_smoothing():
    cfg = _base_dpo_cfg(loss_type="exo_pair", label_smoothing=0.0)
    with pytest.raises(ConfigValidationError, match="exo_pair"):
        _validate_dpo_config(cfg)


def test_robust_requires_label_smoothing_in_range():
    cfg = _base_dpo_cfg(loss_type="robust", label_smoothing=0.0)
    with pytest.raises(ConfigValidationError, match="robust"):
        _validate_dpo_config(cfg)
    cfg = _base_dpo_cfg(loss_type="robust", label_smoothing=0.5)
    with pytest.raises(ConfigValidationError, match="robust"):
        _validate_dpo_config(cfg)
    cfg = _base_dpo_cfg(loss_type="robust", label_smoothing=0.6)
    with pytest.raises(ConfigValidationError, match="robust"):
        _validate_dpo_config(cfg)
    # Valid case
    cfg = _base_dpo_cfg(loss_type="robust", label_smoothing=0.1)
    _validate_dpo_config(cfg)


def test_multi_loss_weight_length_mismatch():
    cfg = _base_dpo_cfg(loss_type=["sigmoid", "bco_pair"], loss_weights=[1.0])
    with pytest.raises(ConfigValidationError, match="same length"):
        _validate_dpo_config(cfg)


def test_multi_loss_matching_lengths_passes():
    cfg = _base_dpo_cfg(loss_type=["sigmoid", "bco_pair"], loss_weights=[0.5, 0.5])
    _validate_dpo_config(cfg)


def test_liger_plus_multi_loss_rejected():
    cfg = _base_dpo_cfg(loss_type=["sigmoid", "sft"])
    cfg["training"]["use_liger_kernel"] = True
    with pytest.raises(ConfigValidationError, match="multi-loss"):
        _validate_dpo_config(cfg)


def test_liger_plus_precompute_ref_log_probs_rejected():
    cfg = _base_dpo_cfg(precompute_ref_log_probs=True)
    cfg["training"]["use_liger_kernel"] = True
    with pytest.raises(ConfigValidationError, match="precompute_ref_log_probs"):
        _validate_dpo_config(cfg)


def test_sync_ref_model_with_peft_rejected():
    cfg = _base_dpo_cfg(sync_ref_model=True)
    cfg["lora"]["enabled"] = True
    with pytest.raises(ConfigValidationError, match="PEFT"):
        _validate_dpo_config(cfg)


def test_sync_ref_model_plus_precompute_rejected():
    cfg = _base_dpo_cfg(sync_ref_model=True, precompute_ref_log_probs=True)
    cfg["lora"]["enabled"] = False  # so sync_ref_model isn't blocked by the PEFT check
    cfg["lora"]["method"] = "none"
    with pytest.raises(ConfigValidationError, match="cannot both be true"):
        _validate_dpo_config(cfg)


def test_aot_plus_use_weighting_rejected():
    cfg = _base_dpo_cfg(loss_type="aot", use_weighting=True)
    with pytest.raises(ConfigValidationError, match="use_weighting"):
        _validate_dpo_config(cfg)


def test_aot_in_multi_loss_with_weighting_rejected():
    cfg = _base_dpo_cfg(loss_type=["sigmoid", "aot_unpaired"], use_weighting=True)
    with pytest.raises(ConfigValidationError, match="use_weighting"):
        _validate_dpo_config(cfg)


def test_prompt_length_must_be_less_than_max_length():
    cfg = _base_dpo_cfg()
    cfg["data"]["max_length"] = 512
    cfg["data"]["max_prompt_length"] = 512
    with pytest.raises(ConfigValidationError, match="max_prompt_length"):
        _validate_dpo_config(cfg)


def test_prompt_length_well_under_max_length_passes():
    cfg = _base_dpo_cfg()
    cfg["data"]["max_length"] = 2048
    cfg["data"]["max_prompt_length"] = 1024
    _validate_dpo_config(cfg)
