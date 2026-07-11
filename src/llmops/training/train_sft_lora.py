"""SFT + LoRA training (TRL + PEFT + optional unsloth).

CLI:
    python -m llmops.training.train_sft_lora --config configs/train.yaml [--smoke-test]

Distributed:
    accelerate launch --config_file infra/accelerate/fsdp.yaml \
        -m llmops.training.train_sft_lora --config configs/train.yaml

Surfaces every relevant HuggingFace knob through the config:
- Loader engine (hf / unsloth)
- Quantization (bitsandbytes 4-/8-bit)
- Attention implementation (eager / sdpa / flash_attention_2 / flex_attention)
- PEFT method (lora / dora / ia3 / prompt_tuning / prefix_tuning / p_tuning / adalora / none)
- LoRA variants (rsLoRA, DoRA, QALoRA, init = pissa/loftq/eva)
- Optimizer (adamw_torch / paged_adamw_8bit / adafactor / lion_8bit / ...)
- Loss + regularization (nll/dft/chunked_nll, neftune, assistant-only, completion-only)
- Throughput (Liger kernels, torch_compile, packing, gradient checkpointing kwargs)
- Tracking sinks (report_to passthrough)

Logs full lineage (git SHA, config hash, dataset version, base-model revision,
seed, package versions, GPU info) to MLflow if enabled, plus a JSON sidecar.
"""

from __future__ import annotations

import argparse
import inspect
import json
import sys
from pathlib import Path
from typing import Any

from llmops.common.config import config_hash, flatten, load_yaml
from llmops.common.logging import get_logger
from llmops.common.tracking import get_tracker
from llmops.common.versioning import run_identity
from llmops.features.chat_template import (
    DEFAULT_CHAT_TEMPLATE_VERSION,
    get_chat_template,
)
from llmops.training._metrics_callback import TrainingMetricsCallback

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Smoke-test overrides
# ---------------------------------------------------------------------------
def _smoke_overrides(cfg: dict[str, Any]) -> dict[str, Any]:
    """Patch cfg in-place with CPU-friendly tiny-model settings for smoke runs."""
    log.warning("SMOKE MODE: overriding model + training settings for CPU smoke test")
    cfg.setdefault("model", {})
    cfg.setdefault("training", {})
    cfg.setdefault("lora", {})
    cfg["model"]["base_model"] = cfg["model"].get(
        "smoke_base_model", "HuggingFaceTB/SmolLM2-135M-Instruct"
    )
    # Force the most-compatible path on smoke so it runs anywhere.
    cfg["model"]["loader"] = "hf"
    cfg["model"]["quantization"] = None
    cfg["model"]["attn_impl"] = "eager"
    cfg["training"].update(
        {
            "epochs": 1,
            "per_device_train_batch_size": 1,
            "gradient_accumulation_steps": 1,
            "max_steps": 2,
            "logging_steps": 1,
            "save_strategy": "no",
            "eval_strategy": "no",
            "bf16": False,
            "fp16": False,
            "gradient_checkpointing": False,
            "learning_rate": 2.0e-4,
            "warmup_ratio": 0.0,
            "use_liger_kernel": False,
            "torch_compile": False,
            "report_to": "none",
            "neftune_noise_alpha": 0.0,
            "loss_type": "nll",
        }
    )
    cfg["lora"].update(
        {
            "r": 4,
            "alpha": 8,
            "dropout": 0.0,
            "method": "lora",
            "use_dora": False,
            "use_rslora": False,
            "use_qalora": False,
            "init_lora_weights": True,
        }
    )
    cfg.setdefault("data", {}).update({"limit": 4, "max_seq_length": 256})
    cfg.setdefault("output", {}).update(
        {"adapter_dir": "artifacts/adapter-smoke", "model_dir": "artifacts/model-smoke"}
    )
    return cfg


# ---------------------------------------------------------------------------
# Config validator + effective-config summary
# ---------------------------------------------------------------------------
class ConfigValidationError(ValueError):
    """Raised when configs/train.yaml is internally inconsistent or asks for
    something this environment can't deliver. Always actionable — include a fix
    in the message."""


_BNB_BF16_NAMES = {"bfloat16", "bf16"}
_BNB_FP16_NAMES = {"float16", "fp16"}


def _validate_config(cfg: dict[str, Any]) -> None:
    """Hard-fail on misconfigurations BEFORE any expensive model load.

    The validator never mutates `cfg` and never silently auto-corrects. It either
    raises ConfigValidationError with a specific fix, or returns silently.
    Smoke-mode overrides run before this and intentionally set CPU-safe values,
    so they sail through.
    """
    import torch

    model_cfg = cfg.get("model") or {}
    train_cfg = cfg.get("training") or {}
    lora_cfg = cfg.get("lora") or {}

    has_cuda = torch.cuda.is_available()
    bf16 = bool(train_cfg.get("bf16", False))
    fp16 = bool(train_cfg.get("fp16", False))
    quant = model_cfg.get("quantization") or None
    attn_impl = model_cfg.get("attn_impl") or "sdpa"
    loader = (model_cfg.get("loader") or "hf").lower()

    # 1. Can't have both bf16 and fp16
    if bf16 and fp16:
        raise ConfigValidationError(
            "training.bf16 and training.fp16 are both true. Pick exactly one. "
            "Use bf16 on Ampere+ GPUs (A100/H100/RTX 30/40-series); fp16 on T4/V100."
        )

    # 2. Mixed precision requires CUDA
    if (bf16 or fp16) and not has_cuda:
        which = "bf16" if bf16 else "fp16"
        raise ConfigValidationError(
            f"training.{which} requires a CUDA GPU. None detected. "
            "Either set training.bf16 and training.fp16 to false, or run on a "
            "CUDA machine. (On CPU smoke, use the --smoke-test flag — it auto-disables mixed precision.)"
        )

    # 3. Quantization requires CUDA (bitsandbytes is GPU-only)
    if quant and not has_cuda:
        raise ConfigValidationError(
            "model.quantization is set but no CUDA GPU is available. "
            "bitsandbytes only runs on CUDA. Either set model.quantization to null, "
            "or run on a CUDA machine."
        )

    # 4. QLoRA dtype alignment: bnb_4bit_compute_dtype must match the trainer's mixed precision
    if quant and quant.get("load_in_4bit"):
        compute_dtype = str(quant.get("bnb_4bit_compute_dtype", "bfloat16")).lower()
        wants_bf16 = compute_dtype in _BNB_BF16_NAMES
        wants_fp16 = compute_dtype in _BNB_FP16_NAMES
        if wants_bf16 and not bf16:
            raise ConfigValidationError(
                f"QLoRA dtype mismatch: model.quantization.bnb_4bit_compute_dtype="
                f"{quant.get('bnb_4bit_compute_dtype')!r} requires training.bf16=true, "
                f"but you have bf16={bf16}, fp16={fp16}. "
                "Either set training.bf16: true (recommended on Ampere+) "
                "or set bnb_4bit_compute_dtype: float16 to match fp16."
            )
        if wants_fp16 and not fp16:
            raise ConfigValidationError(
                f"QLoRA dtype mismatch: model.quantization.bnb_4bit_compute_dtype="
                f"{quant.get('bnb_4bit_compute_dtype')!r} requires training.fp16=true, "
                f"but you have bf16={bf16}, fp16={fp16}. "
                "Either set training.fp16: true, or change bnb_4bit_compute_dtype to bfloat16 "
                "(recommended on Ampere+)."
            )
        if not (wants_bf16 or wants_fp16):
            raise ConfigValidationError(
                f"model.quantization.bnb_4bit_compute_dtype={compute_dtype!r} is not supported. "
                "Use 'bfloat16' (Ampere+) or 'float16' (T4/V100)."
            )

    # 5a. Neuron-incompatible config combos (checked BEFORE universal package checks
    # so the message says "Trainium uses its own kernels", not "install flash-attn").
    if loader == "neuron":
        if quant:
            raise ConfigValidationError(
                "model.quantization is set with model.loader=neuron. "
                "Trainium does NOT support bitsandbytes — drop the quantization block "
                "or switch model.loader to 'hf' on a CUDA box."
            )
        if attn_impl == "flash_attention_2":
            raise ConfigValidationError(
                "model.attn_impl=flash_attention_2 is incompatible with model.loader=neuron. "
                "Trainium uses its own attention kernels. Set model.attn_impl to 'eager' (recommended on Neuron) "
                "or run on CUDA."
            )
        if train_cfg.get("use_liger_kernel"):
            raise ConfigValidationError(
                "training.use_liger_kernel=true is incompatible with model.loader=neuron. "
                "Liger Triton kernels are CUDA-only; on Neuron, set training.use_liger_kernel: false."
            )
        if train_cfg.get("torch_compile"):
            raise ConfigValidationError(
                "training.torch_compile=true is not supported with model.loader=neuron. "
                "NeuronTrainer handles its own graph compilation; set training.torch_compile: false."
            )
        bnb_optims = {"paged_adamw_8bit", "paged_adamw_32bit", "lion_8bit", "adamw_8bit"}
        if (train_cfg.get("optim") or "").lower() in bnb_optims:
            raise ConfigValidationError(
                f"training.optim={train_cfg.get('optim')!r} requires bitsandbytes (CUDA-only) "
                "and is incompatible with model.loader=neuron. Use 'adamw_torch' or 'adafactor'."
            )

    # 5. attn_impl=flash_attention_2 requires flash-attn package
    if attn_impl == "flash_attention_2":
        try:
            import flash_attn  # noqa: F401
        except ImportError:
            raise ConfigValidationError(
                "model.attn_impl=flash_attention_2 requires the flash-attn package, "
                "which is not installed. Install with `pip install flash-attn --no-build-isolation` "
                "on a Linux+CUDA box, or set model.attn_impl: sdpa (Torch ≥2.1 native, almost as fast)."
            ) from None
        if not has_cuda:
            raise ConfigValidationError(
                "model.attn_impl=flash_attention_2 requires CUDA. None detected. "
                "Set model.attn_impl: sdpa or eager."
            )

    # 6. use_liger_kernel requires liger-kernel + Triton (Linux+CUDA only currently)
    if train_cfg.get("use_liger_kernel"):
        try:
            import liger_kernel  # noqa: F401
        except ImportError:
            raise ConfigValidationError(
                "training.use_liger_kernel is true but liger-kernel is not installed. "
                "Install with `pip install liger-kernel` (requires Triton, Linux+CUDA only). "
                "Set training.use_liger_kernel: false to disable."
            ) from None
        if not has_cuda:
            raise ConfigValidationError(
                "training.use_liger_kernel requires CUDA. None detected. "
                "Set training.use_liger_kernel: false."
            )

    # 7. torch_compile requires Triton (no Windows wheels)
    if train_cfg.get("torch_compile"):
        try:
            import triton  # noqa: F401
        except ImportError:
            raise ConfigValidationError(
                "training.torch_compile=true requires Triton, which is not installed. "
                "Triton has no Windows wheels — to use torch.compile, run on Linux/WSL2 with "
                "`pip install triton`. Or set training.torch_compile: false."
            ) from None

    # 8. loader=unsloth requires CUDA + unsloth package
    if loader == "unsloth":
        if not has_cuda:
            raise ConfigValidationError(
                "model.loader=unsloth requires CUDA. None detected. "
                "Set model.loader: hf or run on Linux+CUDA."
            )
        try:
            import unsloth  # noqa: F401
        except ImportError:
            raise ConfigValidationError(
                "model.loader=unsloth requires the unsloth package. "
                "Install with `pip install unsloth` (Linux+CUDA only). "
                "Or set model.loader: hf."
            ) from None

    # 8b. loader=neuron — the combo checks fired in #5a above. Here we just check
    # that the package is installed (last line of defense before runtime).
    elif loader == "neuron":
        try:
            import optimum.neuron  # noqa: F401
        except ImportError:
            raise ConfigValidationError(
                "model.loader=neuron requires the 'optimum-neuron' package. "
                "Install with `pip install optimum-neuron` on a Trainium instance "
                "(trn1.32xlarge / trn1n.32xlarge). "
                "Or set model.loader: hf for CUDA/CPU."
            ) from None

    elif loader != "hf":
        raise ConfigValidationError(
            f"model.loader={loader!r} is not supported. Use 'hf', 'unsloth', or 'neuron'."
        )

    # 9. Sequence/loss sanity: assistant_only_loss needs a chat template w/ generation markers
    if train_cfg.get("assistant_only_loss") and train_cfg.get("completion_only_loss"):
        # Allowed per TRL docs, but only with conversational prompt-completion. Inform.
        log.info(
            "Both assistant_only_loss and completion_only_loss are true. "
            "This is valid only for conversational prompt-completion datasets."
        )

    # 10. PEFT/quant interaction: 8-bit LoRA training is supported, 4-bit LoRA = QLoRA.
    if quant and quant.get("load_in_4bit") and not lora_cfg.get("enabled", True):
        raise ConfigValidationError(
            "model.quantization.load_in_4bit=true with lora.enabled=false is "
            "full-precision training on a 4-bit-quantized base. That's not supported — "
            "4-bit weights can't be trained directly. Either enable LoRA (the usual QLoRA path) "
            "or disable quantization."
        )

    # 11. DPO loss validation lives in train_dpo._validate_dpo_config


def _print_effective_config(cfg: dict[str, Any]) -> None:
    """One-shot dump of the resolved settings so the user sees what's about to run.

    Printed BEFORE model load — if you spot something wrong, ctrl-C costs you seconds,
    not minutes."""
    import torch

    model_cfg = cfg.get("model", {})
    train_cfg = cfg.get("training", {})
    lora_cfg = cfg.get("lora", {})
    data_cfg = cfg.get("data", {})
    quant = model_cfg.get("quantization") or None

    has_cuda = torch.cuda.is_available()
    gpu = (
        f"{torch.cuda.get_device_name(0)} ({torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB)"
        if has_cuda
        else "none (CPU)"
    )

    peft_method = (
        "full FT" if not lora_cfg.get("enabled", True) else (lora_cfg.get("method") or "lora")
    )
    precision = "bf16" if train_cfg.get("bf16") else ("fp16" if train_cfg.get("fp16") else "fp32")
    quant_str = "off"
    if quant:
        if quant.get("load_in_4bit"):
            quant_str = f"4-bit ({quant.get('bnb_4bit_quant_type', 'nf4')}, compute={quant.get('bnb_4bit_compute_dtype', 'bfloat16')})"
        elif quant.get("load_in_8bit"):
            quant_str = "8-bit (LLM.int8)"

    lines = [
        "=" * 72,
        "  Effective training configuration",
        "=" * 72,
        f"  run_name             : {cfg.get('run_name', '(unset)')}",
        f"  base_model           : {model_cfg.get('base_model')}",
        f"  loader               : {model_cfg.get('loader', 'hf')}",
        f"  attn_impl            : {model_cfg.get('attn_impl', 'sdpa')}",
        f"  quantization         : {quant_str}",
        f"  precision            : {precision}",
        f"  peft method          : {peft_method}"
        + (
            f" (r={lora_cfg.get('r')}, alpha={lora_cfg.get('alpha')})"
            if lora_cfg.get("enabled", True)
            else ""
        ),
        f"  optimizer            : {train_cfg.get('optim', 'adamw_torch')}",
        f"  lr / wd / clip       : {train_cfg.get('learning_rate', 2e-5)} / {train_cfg.get('weight_decay', 0.01)} / {train_cfg.get('max_grad_norm', 1.0)}",
        f"  scheduler            : {train_cfg.get('lr_scheduler_type', 'linear')} (warmup={train_cfg.get('warmup_ratio', 0.03)})",
        f"  epochs / max_steps   : {train_cfg.get('epochs', 1)} / {train_cfg.get('max_steps', 'unset')}",
        f"  batch (per-dev * ga) : {train_cfg.get('per_device_train_batch_size', 2)} * {train_cfg.get('gradient_accumulation_steps', 16)}",
        f"  max_seq_length       : {data_cfg.get('max_seq_length', 4096)}",
        f"  loss_type            : {train_cfg.get('loss_type', 'nll')}"
        + (
            f", neftune_alpha={train_cfg['neftune_noise_alpha']}"
            if train_cfg.get("neftune_noise_alpha")
            else ""
        ),
        f"  gc / liger / compile : "
        f"{train_cfg.get('gradient_checkpointing', False)} / "
        f"{train_cfg.get('use_liger_kernel', False)} / "
        f"{train_cfg.get('torch_compile', False)}",
        f"  parallelism          : {(cfg.get('parallelism') or {}).get('profile', 'single')}",
        f"  report_to            : {train_cfg.get('report_to', 'none')}",
        f"  hardware             : {gpu}",
    ]
    estimate_line = _try_estimate_cost(cfg)
    if estimate_line:
        lines.append(f"  estimate             : {estimate_line}")
    lines.append("=" * 72)
    for line in lines:
        log.info(line)


def _try_estimate_cost(cfg: dict[str, Any]) -> str | None:
    """Invoke the skill's stdlib cost estimator and return its one-line summary.

    Best-effort: if the skill isn't installed, returns None silently.
    """
    import contextlib
    import subprocess
    import tempfile

    import yaml

    skill_script = (
        Path.home() / ".claude" / "skills" / "puffin-finetune" / "scripts" / "estimate_cost.py"
    )
    if not skill_script.exists():
        return None

    # Write the resolved cfg to a temp YAML so the estimator can parse it
    # (handles env-var-interpolated values consistently with what trainer sees).
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            yaml.safe_dump(cfg, f, sort_keys=False)
            tmp_path = f.name
        try:
            out = subprocess.run(
                [sys.executable, str(skill_script), "--config", tmp_path],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip().splitlines()[-1]
        finally:
            with contextlib.suppress(OSError):
                Path(tmp_path).unlink()
    except Exception as e:
        log.debug("cost estimator unavailable: %s", e)
    return None


# ---------------------------------------------------------------------------
# Config -> HF builders
# ---------------------------------------------------------------------------
def _build_quantization_config(quant_cfg: dict[str, Any] | None) -> Any | None:
    """Return a transformers QuantizationConfig or None.

    Only bitsandbytes is supported here because that's the only backend HF
    supports for fine-tuning (gptq/awq are inference-only).
    """
    if not quant_cfg:
        return None

    backend = (quant_cfg.get("backend") or "bitsandbytes").lower()
    if backend != "bitsandbytes":
        raise ValueError(
            f"quantization.backend={backend!r} is not supported for training. "
            "Only 'bitsandbytes' supports QLoRA-style fine-tuning. GPTQ and AWQ "
            "are inference-only."
        )

    import torch
    from transformers import BitsAndBytesConfig

    compute_dtype_str = str(quant_cfg.get("bnb_4bit_compute_dtype", "bfloat16")).lower()
    compute_dtype = {
        "bfloat16": torch.bfloat16,
        "bf16": torch.bfloat16,
        "float16": torch.float16,
        "fp16": torch.float16,
        "float32": torch.float32,
        "fp32": torch.float32,
    }.get(compute_dtype_str, torch.bfloat16)

    return BitsAndBytesConfig(
        load_in_4bit=bool(quant_cfg.get("load_in_4bit", False)),
        load_in_8bit=bool(quant_cfg.get("load_in_8bit", False)),
        bnb_4bit_quant_type=str(quant_cfg.get("bnb_4bit_quant_type", "nf4")),
        bnb_4bit_compute_dtype=compute_dtype,
        bnb_4bit_use_double_quant=bool(quant_cfg.get("bnb_4bit_use_double_quant", True)),
    )


def _resolve_dtype(train_cfg: dict[str, Any]) -> Any:
    """Pick torch dtype based on precision flags and CUDA availability."""
    import torch

    if train_cfg.get("bf16") and torch.cuda.is_available():
        return torch.bfloat16
    if train_cfg.get("fp16") and torch.cuda.is_available():
        return torch.float16
    return "auto"


def _build_model_init_kwargs(
    model_cfg: dict[str, Any], train_cfg: dict[str, Any]
) -> dict[str, Any]:
    """Build the kwargs dict that will be passed to from_pretrained."""
    import torch

    kwargs: dict[str, Any] = {
        "revision": model_cfg.get("revision", "main"),
        "trust_remote_code": bool(model_cfg.get("trust_remote_code", False)),
    }

    # dtype keyword: transformers ≥4.45 prefers `dtype`; older uses `torch_dtype`.
    # Probe what's accepted to stay compatible.
    from transformers import AutoModelForCausalLM as _AMC

    sig_params = inspect.signature(_AMC.from_pretrained).parameters
    dtype_kwarg = "dtype" if "dtype" in sig_params else "torch_dtype"
    kwargs[dtype_kwarg] = _resolve_dtype(train_cfg)

    # device_map only on CUDA (CPU device_map='auto' triggers warnings + slowness).
    if torch.cuda.is_available():
        kwargs["device_map"] = "auto"

    attn_impl = model_cfg.get("attn_impl") or "sdpa"
    if attn_impl not in {"eager", "sdpa", "flash_attention_2", "flex_attention"}:
        raise ValueError(f"Unknown attn_impl={attn_impl!r}")
    kwargs["attn_implementation"] = attn_impl

    quant_config = _build_quantization_config(model_cfg.get("quantization"))
    if quant_config is not None:
        kwargs["quantization_config"] = quant_config

    return kwargs


def _load_model_and_tokenizer(model_cfg: dict[str, Any], train_cfg: dict[str, Any]):
    """Load (model, tokenizer) via the configured engine.

    Engines:
        hf       - AutoModelForCausalLM + AutoTokenizer (default)
        unsloth  - FastLanguageModel.from_pretrained (Linux+CUDA only)
        neuron   - optimum-neuron model loader (AWS Trainium only)
    """
    loader = (model_cfg.get("loader") or "hf").lower()
    base_model = model_cfg["base_model"]
    init_kwargs = _build_model_init_kwargs(model_cfg, train_cfg)

    if loader == "neuron":
        # optimum-neuron uses custom modeling implementations from
        # optimum.neuron.models.training. Some architectures have native Neuron
        # implementations; others fall back to vanilla AutoModelForCausalLM.
        try:
            from optimum.neuron import NeuronTrainingArguments  # noqa: F401
            from optimum.neuron.models.training import (  # type: ignore
                AutoModelForCausalLM as NeuronAutoModelForCausalLM,
            )
        except ImportError as e:
            raise ImportError(
                "loader=neuron requires the 'optimum-neuron' package on a Trainium "
                "instance. Install with `pip install optimum-neuron` and run on "
                "trn1.32xlarge / trn1n.32xlarge."
            ) from e
        from transformers import AutoTokenizer

        log.info("loading tokenizer for %s (neuron)", base_model)
        tokenizer = AutoTokenizer.from_pretrained(
            base_model,
            revision=model_cfg.get("tokenizer_revision", "main"),
            use_fast=True,
            trust_remote_code=bool(model_cfg.get("trust_remote_code", False)),
        )
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token

        log.info("loading base model %s on Neuron (Trainium)", base_model)
        # NeuronAutoModelForCausalLM uses native Neuron parallelism; we'll pass
        # the trn_config built inside _build_neuron_training_args during arg construction.
        model = NeuronAutoModelForCausalLM.from_pretrained(
            base_model,
            revision=model_cfg.get("revision", "main"),
            trust_remote_code=bool(model_cfg.get("trust_remote_code", False)),
        )
        return model, tokenizer

    if loader == "unsloth":
        import torch

        if not torch.cuda.is_available():
            raise RuntimeError(
                "loader=unsloth requires CUDA. unsloth supports Linux + NVIDIA GPUs only. "
                "Set model.loader: hf or run on a CUDA machine."
            )
        try:
            from unsloth import FastLanguageModel
        except ImportError as e:
            raise ImportError(
                "loader=unsloth requires the 'unsloth' package. Install with "
                "`pip install unsloth` (Linux + CUDA only)."
            ) from e
        quant = model_cfg.get("quantization") or {}
        load_in_4bit = bool(quant.get("load_in_4bit", False))
        load_in_8bit = bool(quant.get("load_in_8bit", False))
        max_seq_length = int(train_cfg.get("max_seq_length", 2048))
        log.info("loading model via unsloth: %s", base_model)
        model, tokenizer = FastLanguageModel.from_pretrained(
            model_name=base_model,
            max_seq_length=max_seq_length,
            dtype=None,  # auto-detect
            load_in_4bit=load_in_4bit,
            load_in_8bit=load_in_8bit,
        )
        return model, tokenizer

    if loader != "hf":
        raise ValueError(f"Unknown model.loader={loader!r}; expected 'hf', 'unsloth', or 'neuron'.")

    from transformers import AutoModelForCausalLM, AutoTokenizer

    log.info("loading tokenizer for %s", base_model)
    tokenizer = AutoTokenizer.from_pretrained(
        base_model,
        revision=model_cfg.get("tokenizer_revision", "main"),
        use_fast=True,
        trust_remote_code=bool(model_cfg.get("trust_remote_code", False)),
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    log.info(
        "loading base model %s (attn=%s, quant=%s)",
        base_model,
        init_kwargs.get("attn_implementation"),
        "on" if "quantization_config" in init_kwargs else "off",
    )
    model = AutoModelForCausalLM.from_pretrained(base_model, **init_kwargs)
    return model, tokenizer


def _build_peft_config(lora_cfg: dict[str, Any]):
    """Construct a peft.PeftConfig from the lora block.

    Returns None if method=='none' or enabled=False (full fine-tune).
    """
    if not lora_cfg.get("enabled", True):
        return None

    method = (lora_cfg.get("method") or "lora").lower()
    if method == "none":
        return None

    if method in {"lora", "dora"}:
        from peft import LoraConfig

        # The two methods only differ by the use_dora flag; allow either form.
        use_dora = method == "dora" or bool(lora_cfg.get("use_dora", False))
        init = lora_cfg.get("init_lora_weights", True)
        # peft expects True/False or a literal string ("gaussian", "pissa",
        # "loftq", "eva", "olora"). YAML may serialize bools as strings.
        if isinstance(init, str) and init.lower() in {"true", "false"}:
            init = init.lower() == "true"
        kwargs: dict[str, Any] = dict(
            task_type="CAUSAL_LM",
            r=int(lora_cfg.get("r", 16)),
            lora_alpha=int(lora_cfg.get("alpha", 32)),
            lora_dropout=float(lora_cfg.get("dropout", 0.05)),
            target_modules=lora_cfg.get("target_modules", ["q_proj", "k_proj", "v_proj", "o_proj"]),
            bias=str(lora_cfg.get("bias", "none")),
            use_dora=use_dora,
            use_rslora=bool(lora_cfg.get("use_rslora", False)),
            init_lora_weights=init,
            modules_to_save=lora_cfg.get("modules_to_save") or None,
        )
        # QALoRA is opt-in and only on newer peft.
        params = inspect.signature(LoraConfig).parameters
        if lora_cfg.get("use_qalora") and "use_qalora" in params:
            kwargs["use_qalora"] = True
            if "qalora_group_size" in params:
                kwargs["qalora_group_size"] = int(lora_cfg.get("qalora_group_size", 16))
        return LoraConfig(**kwargs)

    if method == "ia3":
        from peft import IA3Config

        # IA3 requires feedforward_modules to be a subset of target_modules.
        target = lora_cfg.get("target_modules") or ["k_proj", "v_proj", "down_proj"]
        feedforward = lora_cfg.get("feedforward_modules") or ["down_proj"]
        # Auto-expand target_modules to include feedforward entries if needed.
        target = list(dict.fromkeys(list(target) + [m for m in feedforward if m not in target]))
        return IA3Config(
            task_type="CAUSAL_LM",
            target_modules=target,
            feedforward_modules=feedforward,
        )

    if method == "prompt_tuning":
        from peft import PromptTuningConfig

        return PromptTuningConfig(
            task_type="CAUSAL_LM",
            num_virtual_tokens=int(lora_cfg.get("num_virtual_tokens", 20)),
        )

    if method == "prefix_tuning":
        from peft import PrefixTuningConfig

        return PrefixTuningConfig(
            task_type="CAUSAL_LM",
            num_virtual_tokens=int(lora_cfg.get("num_virtual_tokens", 20)),
        )

    if method == "p_tuning":
        from peft import PromptEncoderConfig

        return PromptEncoderConfig(
            task_type="CAUSAL_LM",
            num_virtual_tokens=int(lora_cfg.get("num_virtual_tokens", 20)),
        )

    if method == "adalora":
        from peft import AdaLoraConfig

        ada = lora_cfg.get("adalora") or {}
        # AdaLoRA needs `total_step > 0` to schedule rank reallocation;
        # default to 1000 if the user didn't override.
        return AdaLoraConfig(
            task_type="CAUSAL_LM",
            lora_alpha=int(lora_cfg.get("alpha", 32)),
            lora_dropout=float(lora_cfg.get("dropout", 0.05)),
            target_modules=lora_cfg.get("target_modules"),
            target_r=int(ada.get("target_r", 8)),
            init_r=int(ada.get("init_r", 12)),
            tinit=int(ada.get("tinit", 0)),
            tfinal=int(ada.get("tfinal", 0)),
            deltaT=int(ada.get("deltaT", 1)),
            total_step=int(ada.get("total_step", 1000)),
        )

    raise ValueError(f"Unknown lora.method={method!r}")


def _wrap_with_peft(model: Any, peft_config: Any, lora_cfg: dict[str, Any], loader: str) -> Any:
    """Wrap a base model with the chosen PEFT method.

    Unsloth has its own LoRA injector that fuses Triton kernels; use it when
    loader=unsloth + method in {lora, dora}.
    """
    if peft_config is None:
        return model

    if loader == "unsloth":
        from unsloth import FastLanguageModel

        return FastLanguageModel.get_peft_model(
            model,
            r=int(lora_cfg.get("r", 16)),
            lora_alpha=int(lora_cfg.get("alpha", 32)),
            lora_dropout=float(lora_cfg.get("dropout", 0.0)),
            bias=str(lora_cfg.get("bias", "none")),
            target_modules=lora_cfg.get("target_modules", ["q_proj", "k_proj", "v_proj", "o_proj"]),
            use_gradient_checkpointing=True,
            use_rslora=bool(lora_cfg.get("use_rslora", False)),
            use_dora=bool(lora_cfg.get("use_dora", False)),
            random_state=42,
        )

    from peft import get_peft_model, prepare_model_for_kbit_training

    # Stabilize training when using 4-/8-bit quantization (cast LayerNorms to fp32, etc.)
    has_quant = getattr(model, "quantization_method", None) is not None
    if has_quant:
        model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)

    model = get_peft_model(model, peft_config)
    if hasattr(model, "print_trainable_parameters"):
        model.print_trainable_parameters()
    return model


def _normalize_report_to(value: Any) -> list[str] | str:
    """report_to accepts a string, a list, or 'none' / 'all'."""
    if value is None or value == [] or value == "none":
        return "none"
    if isinstance(value, str):
        return value
    return list(value)


def _build_sft_args(cfg: dict[str, Any], output_dir: Path) -> Any:
    """Construct SFTConfig with every supported knob, falling back gracefully."""
    import torch
    from trl import SFTConfig

    train_cfg = cfg["training"]
    data_cfg = cfg["data"]

    sft_params = inspect.signature(SFTConfig.__init__).parameters
    seq_kwarg = "max_length" if "max_length" in sft_params else "max_seq_length"

    args_kwargs: dict[str, Any] = {
        "output_dir": str(output_dir),
        "num_train_epochs": float(train_cfg.get("epochs", 1)),
        "learning_rate": float(train_cfg.get("learning_rate", 2.0e-5)),
        "weight_decay": float(train_cfg.get("weight_decay", 0.01)),
        "warmup_ratio": float(train_cfg.get("warmup_ratio", 0.03)),
        "lr_scheduler_type": str(train_cfg.get("lr_scheduler_type", "linear")),
        "per_device_train_batch_size": int(train_cfg.get("per_device_train_batch_size", 2)),
        "gradient_accumulation_steps": int(train_cfg.get("gradient_accumulation_steps", 16)),
        "max_grad_norm": float(train_cfg.get("max_grad_norm", 1.0)),
        "optim": str(train_cfg.get("optim", "adamw_torch")),
        "bf16": bool(train_cfg.get("bf16", False)) and torch.cuda.is_available(),
        "fp16": bool(train_cfg.get("fp16", False)) and torch.cuda.is_available(),
        "gradient_checkpointing": bool(train_cfg.get("gradient_checkpointing", False)),
        "seed": int(train_cfg.get("seed", 42)),
        "eval_strategy": train_cfg.get("eval_strategy", "no"),
        "save_strategy": train_cfg.get("save_strategy", "epoch"),
        "logging_steps": int(train_cfg.get("logging_steps", 10)),
        "save_total_limit": int(train_cfg.get("save_total_limit", 3)),
        "report_to": _normalize_report_to(train_cfg.get("report_to")),
        seq_kwarg: int(data_cfg.get("max_seq_length", 4096)),
        "dataset_text_field": "text",
        "packing": bool(train_cfg.get("packing", False)),
    }
    if "max_steps" in train_cfg:
        args_kwargs["max_steps"] = int(train_cfg["max_steps"])
    if "warmup_steps" in train_cfg and "warmup_steps" in sft_params:
        args_kwargs["warmup_steps"] = int(train_cfg["warmup_steps"])

    gc_kwargs = train_cfg.get("gradient_checkpointing_kwargs")
    if gc_kwargs and "gradient_checkpointing_kwargs" in sft_params:
        args_kwargs["gradient_checkpointing_kwargs"] = gc_kwargs

    if "torch_compile" in sft_params:
        args_kwargs["torch_compile"] = bool(train_cfg.get("torch_compile", False))

    # SFT-specific knobs (only set if the param exists in this TRL version)
    sft_specific = {
        "neftune_noise_alpha": train_cfg.get("neftune_noise_alpha"),
        "use_liger_kernel": train_cfg.get("use_liger_kernel"),
        "loss_type": train_cfg.get("loss_type"),
        "assistant_only_loss": train_cfg.get("assistant_only_loss"),
        "completion_only_loss": train_cfg.get("completion_only_loss"),
        "optim_args": train_cfg.get("optim_args"),
    }
    for k, v in sft_specific.items():
        if v is None:
            continue
        if k in sft_params:
            args_kwargs[k] = v
        else:
            log.warning("SFTConfig has no %r in this TRL version; ignoring.", k)

    return SFTConfig(**args_kwargs)


def _build_neuron_args(cfg: dict[str, Any], output_dir: Path) -> Any:
    """Construct NeuronTrainingArguments for an AWS Trainium training run.

    optimum-neuron's NeuronTrainer is a drop-in for transformers.Trainer that
    speaks Neuron device parallelism (tensor/pipeline/ZeRO-1). It does NOT
    accept SFTConfig (and thus no packing / completion_only_loss / liger /
    quantization). For SFT on Neuron, we use the standard causal-LM training
    loop with the chat-templated dataset; the trainer treats it like raw text.
    """
    try:
        from optimum.neuron import NeuronTrainingArguments
    except ImportError as e:  # pragma: no cover - requires Trainium runtime
        raise ImportError(
            "loader=neuron requires the 'optimum-neuron' package. "
            "Install with `pip install optimum-neuron` on a Trainium instance."
        ) from e

    train_cfg = cfg["training"]
    neuron_cfg = cfg.get("neuron") or {}

    nta_params = inspect.signature(NeuronTrainingArguments.__init__).parameters

    args_kwargs: dict[str, Any] = {
        "output_dir": str(output_dir),
        "num_train_epochs": float(train_cfg.get("epochs", 1)),
        "learning_rate": float(train_cfg.get("learning_rate", 2.0e-5)),
        "weight_decay": float(train_cfg.get("weight_decay", 0.01)),
        "warmup_ratio": float(train_cfg.get("warmup_ratio", 0.03)),
        "lr_scheduler_type": str(train_cfg.get("lr_scheduler_type", "linear")),
        "per_device_train_batch_size": int(train_cfg.get("per_device_train_batch_size", 1)),
        "gradient_accumulation_steps": int(train_cfg.get("gradient_accumulation_steps", 1)),
        "max_grad_norm": float(train_cfg.get("max_grad_norm", 1.0)),
        "bf16": bool(train_cfg.get("bf16", True)),  # Trainium prefers bf16
        "gradient_checkpointing": bool(train_cfg.get("gradient_checkpointing", True)),
        "seed": int(train_cfg.get("seed", 42)),
        "eval_strategy": train_cfg.get("eval_strategy", "no"),
        "save_strategy": train_cfg.get("save_strategy", "epoch"),
        "logging_steps": int(train_cfg.get("logging_steps", 10)),
        "save_total_limit": int(train_cfg.get("save_total_limit", 3)),
        "report_to": _normalize_report_to(train_cfg.get("report_to")),
        # Neuron-specific parallelism knobs
        "zero_1": bool(neuron_cfg.get("zero_1", True)),
        "tensor_parallel_size": int(neuron_cfg.get("tensor_parallel_size", 1)),
    }

    # Optional Neuron-specific kwargs only added when supported by this version.
    optional = {
        "pipeline_parallel_size": neuron_cfg.get("pipeline_parallel_size"),
        "pipeline_parallel_num_microbatches": neuron_cfg.get("pipeline_parallel_num_microbatches"),
        "disable_sequence_parallel": (
            not bool(neuron_cfg.get("sequence_parallel", True))
            if neuron_cfg.get("sequence_parallel") is not None
            else None
        ),
        "fuse_qkv": neuron_cfg.get("fuse_qkv"),
    }
    for k, v in optional.items():
        if v is None:
            continue
        if k in nta_params:
            args_kwargs[k] = v
        else:
            log.warning("NeuronTrainingArguments has no %r; ignoring.", k)

    if "max_steps" in train_cfg:
        args_kwargs["max_steps"] = int(train_cfg["max_steps"])

    return NeuronTrainingArguments(**args_kwargs)


def _write_lineage(cfg: dict[str, Any], output_dir: Path, smoke_test: bool, loader: str) -> None:
    """Persist lineage.json next to the adapter/model output. Independent of tracker."""
    model_cfg = cfg.get("model", {})
    lora_cfg = cfg.get("lora", {})
    config_h = config_hash(cfg)
    identity = run_identity()
    lineage_path = output_dir / "lineage.json"
    lineage_path.write_text(
        json.dumps(
            {
                "config_hash": config_h,
                "chat_template_version": cfg.get("data", {}).get("chat_template_version"),
                "base_model": model_cfg.get("base_model"),
                "base_model_revision": model_cfg.get("revision", "main"),
                "loader": loader,
                "attn_impl": model_cfg.get("attn_impl", "sdpa"),
                "peft_method": lora_cfg.get("method", "lora"),
                "quantization": model_cfg.get("quantization"),
                "neuron": cfg.get("neuron") if loader == "neuron" else None,
                "smoke_test": smoke_test,
                "identity": identity,
                "config": cfg,
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )


def _train_neuron(
    cfg: dict[str, Any], output_dir: Path, model: Any, tokenizer: Any, dataset: Any
) -> None:
    """Run NeuronTrainer on Trainium hardware. Untestable on non-Neuron machines."""
    try:
        from optimum.neuron import NeuronTrainer
    except ImportError as e:  # pragma: no cover
        raise ImportError("loader=neuron requires the 'optimum-neuron' package.") from e

    args = _build_neuron_args(cfg, output_dir)
    trainer = NeuronTrainer(
        model=model,
        args=args,
        train_dataset=dataset["train"],
        eval_dataset=dataset.get("eval"),
        tokenizer=tokenizer,
    )
    trainer.train()
    trainer.save_model(str(output_dir))
    tokenizer.save_pretrained(str(output_dir))


# ---------------------------------------------------------------------------
# Train entry point
# ---------------------------------------------------------------------------
def train(cfg: dict[str, Any], *, smoke_test: bool = False) -> Path:
    if smoke_test:
        cfg = _smoke_overrides(dict(cfg))

    # Fail-fast validation BEFORE expensive model load.
    _validate_config(cfg)
    _print_effective_config(cfg)

    from trl import SFTTrainer

    from llmops.training.dataset_loader import load_text_dataset

    model_cfg = cfg["model"]
    train_cfg = cfg["training"]
    lora_cfg = cfg.get("lora", {})
    data_cfg = cfg["data"]
    output_cfg = cfg.get("output", {})
    chat_tpl_version = data_cfg.get("chat_template_version", DEFAULT_CHAT_TEMPLATE_VERSION)
    eos_token = data_cfg.get("eos_token", "</s>")

    # Model + tokenizer (engine-aware)
    model, tokenizer = _load_model_and_tokenizer(model_cfg, train_cfg)
    tokenizer.chat_template = get_chat_template(chat_tpl_version)

    # Dataset
    dataset = load_text_dataset(
        data_cfg["train_path"],
        data_cfg.get("eval_path"),
        chat_template_version=chat_tpl_version,
        eos_token=tokenizer.eos_token or eos_token,
        limit=data_cfg.get("limit"),
    )
    log.info(
        "dataset sizes: train=%d eval=%d",
        len(dataset["train"]),
        len(dataset.get("eval", [])) if "eval" in dataset else 0,
    )

    # PEFT (only applied for hf/unsloth; Neuron uses native parallelism instead)
    loader = (model_cfg.get("loader") or "hf").lower()
    if loader != "neuron":
        peft_config = _build_peft_config(lora_cfg)
        model = _wrap_with_peft(model, peft_config, lora_cfg, loader)

    # Training args
    output_dir = Path(output_cfg.get("adapter_dir", "artifacts/adapter"))
    output_dir.mkdir(parents=True, exist_ok=True)

    # Neuron uses a separate trainer entirely. Delegate.
    if loader == "neuron":
        log.info("loader=neuron: dispatching to NeuronTrainer (Trainium)")
        _train_neuron(cfg, output_dir, model, tokenizer, dataset)
        _write_lineage(cfg, output_dir, smoke_test, loader)
        log.info("training complete; outputs saved to %s", output_dir)
        return output_dir

    args = _build_sft_args(cfg, output_dir)

    # Tracking (puffin's MLflow-or-noop wrapper)
    tracker_cfg = cfg.get("tracking", {})
    tracker = get_tracker(tracker_cfg.get("backend"))
    if tracker_cfg.get("experiment_name"):
        tracker.set_experiment(tracker_cfg["experiment_name"])

    run_name = cfg.get("run_name", "puffin-sft-lora")
    config_h = config_hash(cfg)
    identity = run_identity()

    with tracker.start_run(run_name=run_name) as _run:
        tracker.log_params(flatten({**cfg, "_config_hash": config_h}))
        tracker.set_tags(
            {
                "config_hash": config_h,
                "chat_template_version": chat_tpl_version,
                "loader": loader,
                "attn_impl": model_cfg.get("attn_impl", "sdpa"),
                "peft_method": (lora_cfg.get("method") or "lora")
                if lora_cfg.get("enabled", True)
                else "full",
                "git_sha": identity.get("git_sha") or "n/a",
                "git_dirty": str(identity.get("git_dirty")),
                "platform": identity.get("platform"),
                "python": identity.get("python"),
            }
        )
        lineage_path = output_dir / "lineage.json"
        lineage_path.write_text(
            json.dumps(
                {
                    "config_hash": config_h,
                    "chat_template_version": chat_tpl_version,
                    "base_model": model_cfg["base_model"],
                    "base_model_revision": model_cfg.get("revision", "main"),
                    "loader": loader,
                    "attn_impl": model_cfg.get("attn_impl", "sdpa"),
                    "peft_method": lora_cfg.get("method", "lora"),
                    "quantization": model_cfg.get("quantization"),
                    "smoke_test": smoke_test,
                    "identity": identity,
                    "config": cfg,
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )

        sft_params = inspect.signature(SFTTrainer.__init__).parameters
        tok_kwarg = "processing_class" if "processing_class" in sft_params else "tokenizer"
        metrics_cb = TrainingMetricsCallback(
            output_dir=output_dir,
            method="sft",
            run_name=run_name,
            smoke_test=smoke_test,
            base_model=model_cfg["base_model"],
            peft_method=(
                (lora_cfg.get("method") or "lora") if lora_cfg.get("enabled", True) else "full"
            ),
        )
        trainer = SFTTrainer(
            model=model,
            args=args,
            train_dataset=dataset["train"],
            eval_dataset=dataset.get("eval"),
            callbacks=[metrics_cb],
            **{tok_kwarg: tokenizer},
        )
        try:
            trainer.train()
        except BaseException as exc:
            # Capture the failure in the summary so the UI's Runs tab can
            # show it. Re-raise so the CLI still exits non-zero.
            metrics_cb.mark_failed(f"{type(exc).__name__}: {exc}", state=trainer.state)
            raise
        trainer.save_model(str(output_dir))
        tokenizer.save_pretrained(str(output_dir))

        history = getattr(trainer.state, "log_history", [])
        if history:
            last = history[-1]
            metrics = {k: float(v) for k, v in last.items() if isinstance(v, (int, float))}
            if metrics:
                tracker.log_metrics(metrics)
        tracker.log_artifacts(str(output_dir))

    log.info("training complete; adapter saved to %s", output_dir)
    return output_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SFT + LoRA training.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args(argv)
    cfg = load_yaml(args.config)
    train(cfg, smoke_test=args.smoke_test)
    return 0


if __name__ == "__main__":
    sys.exit(main())
