"""Tests for the DPO config builder."""

from __future__ import annotations

from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
trl = pytest.importorskip("trl")
peft = pytest.importorskip("peft")
transformers = pytest.importorskip("transformers")

from llmops.training.train_dpo import _DPO_LOSS_TYPES, _build_dpo_args  # noqa: E402


def _base_cfg(tmp_path, **overrides):
    cfg = {
        "model": {"base_model": "x", "attn_impl": "sdpa"},
        "data": {
            "train_path": "x",
            "max_length": 1024,
            "max_prompt_length": 512,
        },
        "training": {
            "epochs": 1,
            "learning_rate": 5.0e-6,
            "per_device_train_batch_size": 1,
            "gradient_accumulation_steps": 1,
            "bf16": False,
            "fp16": False,
            "gradient_checkpointing": False,
            "seed": 42,
            "logging_steps": 10,
            "save_strategy": "no",
            "eval_strategy": "no",
            "report_to": "none",
            "optim": "adamw_torch",
        },
        "dpo": {"beta": 0.1, "loss_type": "sigmoid"},
    }
    for k, v in overrides.items():
        cfg[k] = {**cfg.get(k, {}), **v}
    return cfg


def test_dpo_loss_type_set(tmp_path: Path):
    cfg = _base_cfg(tmp_path, dpo={"beta": 0.2, "loss_type": "ipo"})
    args = _build_dpo_args(cfg, tmp_path)
    # TRL ≥1.0 coerces string loss_type into a single-element list.
    assert args.loss_type in ("ipo", ["ipo"])
    assert args.beta == 0.2


def test_dpo_rejects_unknown_loss(tmp_path: Path):
    cfg = _base_cfg(tmp_path, dpo={"beta": 0.1, "loss_type": "made-up"})
    with pytest.raises(ValueError, match="loss_type"):
        _build_dpo_args(cfg, tmp_path)


def test_dpo_multi_loss_mpo(tmp_path: Path):
    cfg = _base_cfg(
        tmp_path,
        dpo={
            "beta": 0.1,
            "loss_type": ["sigmoid", "bco_pair", "sft"],
            "loss_weights": [0.8, 0.2, 1.0],
        },
    )
    args = _build_dpo_args(cfg, tmp_path)
    assert args.loss_type == ["sigmoid", "bco_pair", "sft"]


def test_dpo_multi_loss_validates_each(tmp_path: Path):
    cfg = _base_cfg(
        tmp_path,
        dpo={"beta": 0.1, "loss_type": ["sigmoid", "made-up"]},
    )
    with pytest.raises(ValueError, match="made-up"):
        _build_dpo_args(cfg, tmp_path)


def test_dpo_loss_catalogue_has_all_known_types():
    # If TRL adds new ones, this catches the drift.
    expected_subset = {
        "sigmoid",
        "hinge",
        "ipo",
        "bco_pair",
        "robust",
        "sppo_hard",
        "nca_pair",
        "apo_zero",
        "apo_down",
    }
    assert expected_subset.issubset(_DPO_LOSS_TYPES)
