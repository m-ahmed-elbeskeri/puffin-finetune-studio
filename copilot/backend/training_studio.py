"""Training Studio — recipes, knobs, and config materialization.

Powers the copilot's /train page so anyone from "first fine-tune ever" to
"hand-me-the-optimizer" can launch a run:

- RECIPES: curated presets grouped by category (Get started, Efficient,
  Big models, ...). Each is a set of overrides applied on top of the
  project's base config, with plain-English guidance on when to use it.
- KNOBS: a typed schema of every tunable that matters: dotted config path,
  input type, sensible ranges, an `essential` flag, and help text written
  for humans. The UI shows the handful of essential knobs by default and
  reveals the rest on demand.
- materialize(): validates overrides against the knob schema, deep-merges
  them into the base YAML (configs/train.yaml or configs/train_dpo.yaml),
  and writes the result to configs/train_studio.yaml (or the DPO variant)
  with a provenance header. The heavily-commented base configs are never
  touched — they stay the source of truth for defaults.

The launch endpoint then hands the materialized path to the existing
`train_start` tool, so process management, sidecar metrics, and the
dangerous-tool gate all behave exactly like a chat-launched run.
"""
from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


STUDIO_CONFIG = {
    "sft": "configs/train_studio.yaml", "dpo": "configs/train_dpo_studio.yaml",
    "kto": "configs/train_kto_studio.yaml", "reward": "configs/train_reward_studio.yaml",
    "grpo": "configs/train_grpo_studio.yaml", "rloo": "configs/train_rloo_studio.yaml",
}
BASE_CONFIG = {
    "sft": "configs/train.yaml", "dpo": "configs/train_dpo.yaml",
    "kto": "configs/train_kto.yaml", "reward": "configs/train_reward.yaml",
    "grpo": "configs/train_grpo.yaml", "rloo": "configs/train_rloo.yaml",
}
ALL_METHODS = ["sft", "dpo", "kto", "reward", "grpo", "rloo"]
# Methods that share the standard model/LoRA/optimizer surface (everything
# except SFT-only text knobs and the preference/RL-specific loss knobs).
_SHARED_METHODS = ALL_METHODS
CUSTOM_RECIPES_REL = "artifacts/copilot/custom_recipes.json"

# Where a training run can execute. "local" runs on this machine via the
# existing train_start path; the cloud targets generate a submit command that
# takes the materialized studio config (we never auto-submit and spend money).
# Each cloud target declares the fields its submit command needs; the /train
# page renders them as a form and substitutes {config} + every {field.key}
# token into `submit`. Tokens match the real flags the infra scripts accept
# (see infra/cloud/*/submit.py) so the generated command actually runs. We
# never auto-submit — the user runs the command with their own credentials.
CLOUD_TARGETS: list[dict[str, Any]] = [
    {
        "id": "local", "label": "This machine", "kind": "local",
        "env_group": "train",
        "blurb": "Run on the local CPU/GPU. Best for smoke tests and small runs.",
    },
    {
        "id": "sagemaker", "label": "AWS SageMaker", "kind": "cloud",
        "env_group": "aws",
        "blurb": "Managed training on a rented GPU (ml.g5 / ml.p4d) or Trainium.",
        "needs": "AWS credentials and a SageMaker execution-role ARN.",
        "fields": [
            {"key": "instance_type", "label": "Instance type",
             "default": "ml.g5.2xlarge",
             "help": "ml.g5.2xlarge = 1x A10G 24 GB (fits 7-8B QLoRA). "
                     "ml.g5.12xlarge = 4x A10G. ml.p4d.24xlarge = 8x A100 for "
                     "full fine-tunes."},
            {"key": "role", "label": "Execution role ARN",
             "placeholder": "arn:aws:iam::123456789012:role/SageMakerRole",
             "help": "IAM role SageMaker assumes (needs S3 + SageMaker access). "
                     "Leave blank to use the SAGEMAKER_EXECUTION_ROLE env var."},
            {"key": "region", "label": "AWS region", "default": "us-east-1",
             "help": "Region with capacity for that instance type."},
        ],
        "submit": ("python infra/cloud/sagemaker/submit.py --config {config} "
                   "--instance-type {instance_type} --role {role} "
                   "--region {region}"),
        "docs": "https://docs.aws.amazon.com/sagemaker/latest/dg/train-model.html",
    },
    {
        "id": "vertex", "label": "Google Vertex AI", "kind": "cloud",
        "env_group": "gcp",
        "blurb": "Managed training on Vertex AI custom jobs.",
        "needs": ("A puffin container in Artifact Registry (build from "
                  "infra/docker/Dockerfile.train). Vertex has no first-class "
                  "submit.py yet, so this is the documented gcloud path."),
        "fields": [
            {"key": "project", "label": "GCP project id",
             "placeholder": "my-gcp-project", "help": "Your Google Cloud project."},
            {"key": "region", "label": "Region", "default": "us-central1",
             "help": "Region with GPU quota."},
            {"key": "machine_type", "label": "Machine type",
             "default": "g2-standard-8",
             "help": "g2-standard-8 = 1x L4 24 GB. a2-highgpu-1g = 1x A100 40 GB."},
            {"key": "image_uri", "label": "Container image URI",
             "placeholder": "us-central1-docker.pkg.dev/PROJECT/puffin/train:latest",
             "help": "Artifact Registry image built from Dockerfile.train with "
                     "your config baked in (see the Vertex README)."},
        ],
        "submit": ("gcloud ai custom-jobs create --project={project} "
                   "--region={region} --display-name=puffin-sft "
                   "--worker-pool-spec=machine-type={machine_type},"
                   "replica-count=1,container-image-uri={image_uri}"),
        "docs": "https://cloud.google.com/vertex-ai/docs/training/create-custom-job",
    },
    {
        "id": "azureml", "label": "Azure ML", "kind": "cloud",
        "env_group": "azure",
        "blurb": "Managed training as an Azure ML command job.",
        "needs": "az login, a workspace, and a GPU compute cluster.",
        "fields": [
            {"key": "workspace", "label": "Workspace name",
             "placeholder": "my-workspace", "help": "Your Azure ML workspace."},
            {"key": "resource_group", "label": "Resource group",
             "placeholder": "my-resource-group"},
            {"key": "compute", "label": "Compute cluster", "default": "gpu-cluster",
             "help": "Name of your Azure ML GPU compute target."},
        ],
        "submit": ("python infra/cloud/azureml/submit.py --config {config} "
                   "--workspace-name {workspace} "
                   "--resource-group {resource_group} --compute {compute}"),
        "docs": "https://learn.microsoft.com/azure/machine-learning/how-to-train-model",
    },
]


class StudioError(ValueError):
    """Bad recipe id / knob path / value — maps to HTTP 400."""


# ---------------------------------------------------------------------------
# Recipes — curated starting points. `overrides` use dotted knob paths and
# are validated the same way user overrides are.
# ---------------------------------------------------------------------------
RECIPES: list[dict[str, Any]] = [
    {
        "id": "smoke-test",
        "label": "Smoke test",
        "category": "Get started",
        "method": "sft",
        "icon": "zap",
        "tagline": "Prove the whole pipeline works — ~1 minute on CPU.",
        "description": (
            "Runs 2 training steps with a tiny model (SmolLM2-135M) on your "
            "real data. Nothing useful is learned — the point is catching "
            "data, config, and environment problems before you spend GPU "
            "time. Always run this first on a new dataset."
        ),
        "overrides": {},
        "force_smoke": True,
        "needs_gpu": False,
        "est_time": "~1 min on CPU",
    },
    {
        "id": "style-tune",
        "label": "Style & format tune",
        "category": "Get started",
        "method": "sft",
        "icon": "pen-line",
        "tagline": "Teach tone, format, and phrasing with a light touch.",
        "description": (
            "A small, conservative LoRA — low rank, gentle learning rate, "
            "two epochs. Ideal when the base model is already capable and "
            "you want it to answer in your voice: support-agent tone, a "
            "fixed report format, brand phrasing. Hard to break the model "
            "with these settings."
        ),
        "overrides": {
            "training.epochs": 2,
            "training.learning_rate": 1e-4,
            "lora.r": 16,
            "lora.alpha": 32,
            "lora.dropout": 0.05,
            "lora.target_modules": "attention",
        },
        "needs_gpu": False,
        "est_time": "minutes–hours, scales with model + data size",
    },
    {
        "id": "domain-adapt",
        "label": "Domain adaptation",
        "category": "Efficient (LoRA)",
        "method": "sft",
        "icon": "book-open",
        "tagline": "Teach real domain knowledge and vocabulary.",
        "description": (
            "A higher-capacity LoRA: rank 32 across attention AND MLP "
            "layers, three epochs, plus NEFTune noise for better "
            "generalization. Use when the model needs to learn content — "
            "medical/legal/internal terminology, product specifics — not "
            "just style. Needs more data (thousands of examples) to shine."
        ),
        "overrides": {
            "training.epochs": 3,
            "training.learning_rate": 2e-4,
            "training.neftune_noise_alpha": 5.0,
            "lora.r": 32,
            "lora.alpha": 64,
            "lora.target_modules": "all-linear",
        },
        "needs_gpu": True,
        "est_time": "hours, scales with model + data size",
    },
    {
        "id": "qlora-single-gpu",
        "label": "QLoRA — big model, one GPU",
        "category": "Big models",
        "method": "sft",
        "icon": "cpu",
        "tagline": "Fine-tune a 7B–70B model on a single consumer GPU.",
        "description": (
            "Loads the base model in 4-bit NF4 (bitsandbytes), trains LoRA "
            "adapters in bf16, and uses a paged 8-bit optimizer so VRAM "
            "spikes don't OOM. Point model.base_model at a 7B+ model first "
            "— this recipe is wasted on tiny models. Roughly: 7B fits in "
            "~6 GB, 13B in ~10 GB, 70B in ~36 GB of VRAM."
        ),
        "overrides": {
            "model.quantization": "qlora-nf4",
            "training.optim": "paged_adamw_8bit",
            "training.bf16": True,
            "training.gradient_checkpointing": True,
            "training.per_device_train_batch_size": 1,
            "training.gradient_accumulation_steps": 16,
            "lora.r": 16,
            "lora.alpha": 32,
        },
        "needs_gpu": True,
        "est_time": "hours; requires an NVIDIA GPU",
    },
    {
        "id": "full-finetune",
        "label": "Full fine-tune",
        "category": "Maximum capacity",
        "method": "sft",
        "icon": "flame",
        "tagline": "Update every parameter. Maximum capacity, maximum cost.",
        "description": (
            "Disables LoRA and trains all weights with a low learning rate. "
            "Only worth it when adapters demonstrably can't reach your eval "
            "targets — you pay full-model VRAM (rule of thumb ~16× the "
            "parameter count in GB with Adam) and risk catastrophic "
            "forgetting. Run evals against a LoRA baseline first."
        ),
        "overrides": {
            "lora.enabled": False,
            "training.learning_rate": 1e-5,
            "training.epochs": 1,
            "training.bf16": True,
            "training.gradient_checkpointing": True,
        },
        "needs_gpu": True,
        "est_time": "hours–days; heavy VRAM",
    },
    {
        "id": "dpo-align",
        "label": "DPO preference alignment",
        "category": "Preference alignment",
        "method": "dpo",
        "icon": "scale",
        "tagline": "Align on chosen-vs-rejected pairs, after SFT.",
        "description": (
            "Direct Preference Optimization on preference pairs "
            "(prompt / chosen / rejected — see data/processed/"
            "preference_train.jsonl). Use it after SFT when outputs are "
            "competent but you want to steer judgment calls: helpfulness, "
            "tone tradeoffs, refusal style. beta controls how far the "
            "model may drift from its reference (lower = closer)."
        ),
        "overrides": {},
        "needs_gpu": True,
        "est_time": "hours; needs preference-pair data",
    },
]

RECIPES_BY_ID: dict[str, dict[str, Any]] = {r["id"]: r for r in RECIPES}

# Display order for grouping recipe cards on the /train page.
RECIPE_CATEGORIES: list[str] = [
    "Get started", "Efficient (LoRA)", "Big models",
    "Maximum capacity", "Preference alignment",
]
CUSTOM_CATEGORY = "Your recipes"


# ---------------------------------------------------------------------------
# Custom recipes — the user saves their own tuned settings as a named preset.
# Stored per-project so they travel with the project, not the platform.
# ---------------------------------------------------------------------------
def _custom_recipes_path(repo_root: Path) -> Path:
    return Path(repo_root) / CUSTOM_RECIPES_REL


def load_custom_recipes(repo_root: Path) -> list[dict[str, Any]]:
    p = _custom_recipes_path(repo_root)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []


def save_custom_recipe(
    repo_root: Path, *, name: str, method: str,
    overrides: dict[str, Any], description: str = "",
) -> dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise StudioError("recipe name is required")
    if method not in BASE_CONFIG:
        raise StudioError(f"method must be one of {sorted(BASE_CONFIG)}")
    # Validate the overrides the same way a launch would, so a saved recipe
    # can always be loaded and launched.
    validate_overrides(overrides or {}, method=method)
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "recipe"
    rid = f"custom-{method}-{slug}"
    recipe = {
        "id": rid, "label": name, "category": CUSTOM_CATEGORY, "method": method,
        "icon": "sliders", "custom": True,
        "tagline": description.strip() or "Your saved training settings.",
        "description": description.strip() or (
            f"A saved {method.upper()} preset with "
            f"{len(overrides or {})} setting(s) changed from the base config."),
        "overrides": dict(overrides or {}),
        "needs_gpu": bool(overrides and (
            "qlora" in str(overrides.get("model.quantization", "")).lower()
            or overrides.get("lora.enabled") is False)),
        "est_time": "depends on your settings",
    }
    existing = [r for r in load_custom_recipes(repo_root) if r.get("id") != rid]
    existing.append(recipe)
    p = _custom_recipes_path(repo_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    return recipe


def delete_custom_recipe(repo_root: Path, recipe_id: str) -> bool:
    recipes = load_custom_recipes(repo_root)
    kept = [r for r in recipes if r.get("id") != recipe_id]
    if len(kept) == len(recipes):
        return False
    _custom_recipes_path(repo_root).write_text(
        json.dumps(kept, indent=2), encoding="utf-8")
    return True


def _all_recipes(repo_root: Path) -> list[dict[str, Any]]:
    return RECIPES + load_custom_recipes(repo_root)


# ---------------------------------------------------------------------------
# Knobs — the tunable surface. `essential` marks the handful shown by default;
# the rest reveal on demand. `methods` says which trainer the knob applies to.
#
# type in {text, int, float, bool, select}. Selects list `options`; numeric
# knobs may carry min/max/step (advisory: the UI clamps, the backend only
# type-checks so power users can go out of range deliberately via the API).
# ---------------------------------------------------------------------------
KNOBS: list[dict[str, Any]] = [
    # --- Model ------------------------------------------------------------
    {
        "path": "model.base_model", "label": "Base model", "group": "Model",
        "essential": True, "type": "text", "methods": ["sft", "dpo"],
        "help": (
            "The open model you start from, given as a Hugging Face id like "
            "'meta-llama/Llama-3.1-8B-Instruct'. Fine-tuning layers your data on "
            "top of what it already knows. An -Instruct or -chat base already "
            "holds a conversation, so you are mostly shifting its tone and "
            "adding knowledge rather than teaching it to talk."
        ),
        "recommended": (
            "Pick an Instruct model that fits your VRAM: 1B to 3B on a laptop "
            "GPU, 7B to 8B on a 24 GB card with 4-bit quantization. Smoke tests "
            "ignore this and swap in a tiny model automatically."
        ),
    },
    {
        "path": "model.attn_impl", "label": "Attention implementation",
        "group": "Model", "essential": False, "type": "select",
        "options": ["eager", "sdpa", "flash_attention_2", "flex_attention"],
        "methods": ["sft", "dpo"],
        "help": (
            "Which kernel computes attention. This only affects speed and "
            "memory, never the trained result, so use the fastest one your "
            "hardware supports."
        ),
        "option_help": {
            "eager": "Plain PyTorch. Slowest, but works everywhere including CPU.",
            "sdpa": "PyTorch's built-in fused attention. Fast and safe.",
            "flash_attention_2": "Fastest and most memory-efficient on Ampere+ NVIDIA GPUs; needs the flash-attn package.",
            "flex_attention": "Newer flexible kernel for custom masks; still experimental.",
        },
        "recommended": "sdpa. Switch to flash_attention_2 on an RTX 30xx / A100 or newer once flash-attn is installed.",
    },
    {
        "path": "model.loader", "label": "Model loader", "group": "Model",
        "essential": False, "type": "select",
        "options": ["hf", "unsloth", "neuron"], "methods": ["sft", "dpo"],
        "help": (
            "The library that loads and runs the model. It decides which "
            "hardware and speed tricks are available."
        ),
        "option_help": {
            "hf": "Standard Hugging Face transformers. Works on any hardware.",
            "unsloth": "About 2x faster and ~70% less VRAM, but Linux + NVIDIA only.",
            "neuron": "For AWS Trainium (neuron) instances only.",
        },
        "recommended": "hf everywhere. Use unsloth on Linux/NVIDIA when you want the speedup.",
    },
    {
        "path": "model.quantization", "label": "Quantization", "group": "Model",
        "essential": True, "type": "select",
        "options": ["none", "qlora-nf4", "int8"], "methods": ["sft", "dpo"],
        "help": (
            "Compresses the frozen base model to fewer bits so a large model "
            "fits in less VRAM. The adapters you train stay full precision, so "
            "quality loss is small. Only meaningful with LoRA enabled."
        ),
        "option_help": {
            "none": "Full 16-bit weights. Best fidelity; needs the most VRAM.",
            "qlora-nf4": "Loads the base in 4-bit so 7B to 70B fit on one GPU. Pair with LoRA (this is QLoRA).",
            "int8": "8-bit (LLM.int8). A middle ground; less common than nf4.",
        },
        "recommended": "qlora-nf4 for 7B+ on a single consumer GPU; none if the model already fits in 16-bit.",
    },
    # --- Data ---------------------------------------------------------------
    {
        "path": "data.max_seq_length", "label": "Max sequence length",
        "group": "Data", "essential": False, "type": "int",
        "min": 256, "max": 32768, "step": 256, "methods": ["sft"],
        "help": (
            "The longest example, in tokens, the model sees during training. "
            "Longer examples are truncated. Memory grows with this, so it is "
            "the first thing to cut when you hit out-of-memory."
        ),
        "recommended": (
            "Set it just above your 95th-percentile example length (the Data "
            "page reports this). 1024 to 2048 covers most chat data; halve it "
            "to escape OOM."
        ),
    },
    {
        "path": "data.max_length", "label": "Max sequence length",
        "group": "Data", "essential": False, "type": "int",
        "min": 256, "max": 32768, "step": 256, "methods": ["dpo", "kto", "reward"],
        "help": (
            "The longest prompt-plus-response pair, in tokens, kept during "
            "preference training. Longer pairs are trimmed."
        ),
        "recommended": "Large enough to hold your prompt plus the longer of the two answers; 1024 to 2048 is typical.",
    },
    {
        "path": "data.max_prompt_length", "label": "Max prompt length",
        "group": "Data", "essential": False, "type": "int",
        "min": 64, "max": 16384, "step": 64,
        "methods": ["dpo", "kto", "grpo", "rloo"],
        "help": (
            "Token budget reserved for the prompt (the rest is left for the "
            "answer / sampled completion)."
        ),
        "recommended": "Roughly half to two-thirds of max length, sized to your typical prompt.",
    },
    # --- LoRA / PEFT --------------------------------------------------------
    {
        "path": "lora.enabled", "label": "LoRA adapters", "group": "LoRA / PEFT",
        "essential": False, "type": "bool", "methods": ["sft", "dpo"],
        "help": (
            "On: freeze the base model and train small adapter matrices instead "
            "of every weight. This is 10 to 100x cheaper in memory, produces a "
            "few-MB adapter, and rarely loses quality. Off: a full fine-tune of "
            "all weights, which needs far more VRAM and can forget general "
            "skills."
        ),
        "recommended": "On for almost everything. Only turn off for a deliberate full fine-tune with plenty of VRAM.",
    },
    {
        "path": "lora.method", "label": "PEFT method", "group": "LoRA / PEFT",
        "essential": False, "type": "select",
        "options": ["lora", "dora", "ia3", "adalora", "prompt_tuning",
                    "prefix_tuning", "p_tuning", "none"],
        "methods": ["sft", "dpo"],
        "help": (
            "The parameter-efficient technique used for the adapters. They "
            "differ in how many parameters they train and how expressive they "
            "are."
        ),
        "option_help": {
            "lora": "The standard. Low-rank adapters; great quality-to-cost ratio.",
            "dora": "LoRA plus weight-magnitude decomposition. Slightly better, slightly slower.",
            "ia3": "Trains even fewer parameters by rescaling activations. Very light.",
            "adalora": "Redistributes adapter rank across layers during training.",
            "prompt_tuning": "Learns soft prompt tokens only; tiny but limited.",
            "prefix_tuning": "Learns prefix key/value vectors per layer.",
            "p_tuning": "Learns prompt embeddings via a small encoder.",
            "none": "No adapter (only meaningful alongside a full fine-tune).",
        },
        "recommended": "lora. Try dora if you want a small quality bump and can spare the time.",
    },
    {
        "path": "lora.r", "label": "LoRA rank (r)", "group": "LoRA / PEFT",
        "essential": True, "type": "int", "min": 4, "max": 256, "step": 4,
        "methods": ["sft", "dpo"],
        "help": (
            "The size (capacity) of the adapters. Higher rank can learn more, "
            "but costs more memory and time and overfits small datasets faster."
        ),
        "recommended": (
            "8 to 16 for tone and formatting, 32 to 64 to teach real domain "
            "knowledge. Start at 16 and only raise it if the model underfits."
        ),
    },
    {
        "path": "lora.alpha", "label": "LoRA alpha", "group": "LoRA / PEFT",
        "essential": True, "type": "int", "min": 4, "max": 512, "step": 4,
        "methods": ["sft", "dpo"],
        "help": (
            "A gain on the adapters: the effective strength is alpha divided by "
            "rank. It controls how hard the adapters push on the base model."
        ),
        "recommended": "About 2x the rank (r=16 gives alpha=32). Equal to rank is a gentler alternative.",
    },
    {
        "path": "lora.dropout", "label": "LoRA dropout", "group": "LoRA / PEFT",
        "essential": False, "type": "float", "min": 0.0, "max": 0.5,
        "step": 0.01, "methods": ["sft", "dpo"],
        "help": (
            "Randomly drops adapter activations during training to fight "
            "overfitting (memorizing instead of generalizing)."
        ),
        "recommended": "0.05 is typical. Raise toward 0.1 on small datasets; 0 for large ones.",
    },
    {
        "path": "lora.target_modules", "label": "Target layers",
        "group": "LoRA / PEFT", "essential": False, "type": "select",
        "options": ["attention", "all-linear"], "methods": ["sft", "dpo"],
        "help": (
            "Which layers get adapters. More layers means more capacity to "
            "learn content, at a small cost in trainable parameters."
        ),
        "option_help": {
            "attention": "Only the q/k/v/o attention projections. Cheaper; plenty for tone and style.",
            "all-linear": "Also adapts the MLP layers. Best for learning new content; ~1% more trainable params.",
        },
        "recommended": "all-linear for teaching knowledge; attention if you only want a style shift.",
    },
    {
        "path": "lora.use_rslora", "label": "Rank-stabilized LoRA",
        "group": "LoRA / PEFT", "essential": False, "type": "bool",
        "methods": ["sft", "dpo"],
        "help": (
            "Uses a rank-aware scaling for alpha that stays stable at high "
            "ranks, where plain LoRA can become unstable."
        ),
        "recommended": "On when rank is 64 or higher; otherwise leave off.",
    },
    # --- Training schedule ---------------------------------------------------
    {
        "path": "training.epochs", "label": "Epochs", "group": "Training schedule",
        "essential": True, "type": "int", "min": 1, "max": 20, "step": 1,
        "methods": ["sft", "dpo"],
        "help": (
            "How many full passes the trainer makes over your dataset. Too few "
            "underfits; too many memorizes the data and hurts generalization."
        ),
        "recommended": "2 to 3 for most fine-tunes. Use 1 on very large datasets; watch eval loss for the turning point.",
    },
    {
        "path": "training.learning_rate", "label": "Learning rate",
        "group": "Training schedule", "essential": True, "type": "float",
        "min": 1e-7, "max": 1e-2, "methods": ["sft", "dpo"],
        "help": (
            "How big each weight update is. Too high and training diverges or "
            "the model degrades; too low and it barely learns. The single most "
            "important knob to get right."
        ),
        "recommended": (
            "LoRA: 1e-4 to 3e-4. Full fine-tune: 1e-5 to 5e-5. DPO: around 5e-6. "
            "If loss spikes or quality drops, lower this first."
        ),
    },
    {
        "path": "training.per_device_train_batch_size", "label": "Batch size",
        "group": "Training schedule", "essential": True, "type": "int",
        "min": 1, "max": 64, "step": 1, "methods": ["sft", "dpo"],
        "help": (
            "How many examples each GPU processes per step. Larger batches give "
            "smoother, faster training but use more VRAM."
        ),
        "recommended": (
            "The largest that fits in memory (often 1 to 4 for big models). To "
            "grow the effective batch without more VRAM, raise gradient "
            "accumulation instead."
        ),
    },
    {
        "path": "training.gradient_accumulation_steps",
        "label": "Gradient accumulation", "group": "Training schedule",
        "essential": False, "type": "int", "min": 1, "max": 128, "step": 1,
        "methods": ["sft", "dpo"],
        "help": (
            "Runs several batches before each weight update. Effective batch = "
            "batch size x this, so it simulates a big batch on a small GPU for "
            "free (just slower)."
        ),
        "recommended": "Set so effective batch lands around 16 to 32 (e.g. batch 2 x accumulation 8).",
    },
    {
        "path": "training.warmup_ratio", "label": "Warmup ratio",
        "group": "Training schedule", "essential": False, "type": "float",
        "min": 0.0, "max": 0.3, "step": 0.01, "methods": ["sft", "dpo"],
        "help": (
            "The fraction of training spent ramping the learning rate up from "
            "zero, which stabilizes the fragile early steps."
        ),
        "recommended": "0.03 to 0.1. Use the higher end for short runs or high learning rates.",
    },
    {
        "path": "training.lr_scheduler_type", "label": "LR schedule",
        "group": "Training schedule", "essential": False, "type": "select",
        "options": ["linear", "cosine", "constant", "constant_with_warmup",
                    "cosine_with_restarts", "polynomial"],
        "methods": ["sft", "dpo"],
        "help": "How the learning rate changes over the run after warmup.",
        "option_help": {
            "linear": "Decays straight down to zero. Simple and reliable.",
            "cosine": "Smooth cosine decay to near zero. The modern default.",
            "constant": "Holds the learning rate fixed the whole time.",
            "constant_with_warmup": "Warms up, then holds constant.",
            "cosine_with_restarts": "Cosine decay that periodically jumps back up.",
            "polynomial": "Polynomial decay curve; rarely needed.",
        },
        "recommended": "cosine for most runs; linear is a fine, predictable alternative.",
    },
    # --- Optimizer ------------------------------------------------------------
    {
        "path": "training.optim", "label": "Optimizer", "group": "Optimizer",
        "essential": False, "type": "select",
        "options": ["adamw_torch", "adamw_torch_fused", "paged_adamw_8bit",
                    "paged_adamw_32bit", "adafactor", "lion_8bit"],
        "methods": ["sft", "dpo"],
        "help": (
            "The algorithm that turns gradients into weight updates. They trade "
            "off speed, memory, and how much optimizer state they store."
        ),
        "option_help": {
            "adamw_torch": "The safe, well-tested default.",
            "adamw_torch_fused": "Same math, fused CUDA kernels; faster on GPU.",
            "paged_adamw_8bit": "8-bit optimizer state paged to CPU. Big VRAM savings; the QLoRA companion.",
            "paged_adamw_32bit": "Paged, full-precision state. Saves VRAM with less compression.",
            "adafactor": "Very low memory, no per-parameter momentum. Good for huge models.",
            "lion_8bit": "Lion optimizer in 8-bit; light and sometimes faster to converge.",
        },
        "recommended": "adamw_torch normally; paged_adamw_8bit when using QLoRA or fighting for VRAM.",
    },
    {
        "path": "training.weight_decay", "label": "Weight decay",
        "group": "Optimizer", "essential": False, "type": "float",
        "min": 0.0, "max": 0.3, "step": 0.005, "methods": ["sft", "dpo"],
        "help": (
            "Gently pulls weights toward zero each step to discourage "
            "overfitting (a form of regularization)."
        ),
        "recommended": "0.01 for SFT. 0 for DPO.",
    },
    {
        "path": "training.max_grad_norm", "label": "Gradient clipping",
        "group": "Optimizer", "essential": False, "type": "float",
        "min": 0.1, "max": 10.0, "step": 0.1, "methods": ["sft", "dpo"],
        "help": (
            "Caps the size of each update so one bad batch cannot blow up "
            "training. Lower is more conservative."
        ),
        "recommended": "1.0 is standard. Drop to 0.3 to 0.5 if you see loss spikes.",
    },
    # --- Memory & speed ---------------------------------------------------------
    {
        "path": "training.bf16", "label": "bf16 precision", "group": "Memory & speed",
        "essential": False, "type": "bool", "methods": ["sft", "dpo"],
        "help": (
            "Trains in 16-bit brain-float: about half the memory and faster on "
            "modern GPUs, with the wide numeric range that makes it stable."
        ),
        "recommended": "On for any RTX 30xx / A100 or newer GPU. Off on CPU or older cards (use fp16 there).",
    },
    {
        "path": "training.fp16", "label": "fp16 precision", "group": "Memory & speed",
        "essential": False, "type": "bool", "methods": ["sft", "dpo"],
        "help": (
            "The older 16-bit format for pre-Ampere GPUs. Narrower range than "
            "bf16, so slightly more prone to overflow. Never enable both."
        ),
        "recommended": "Only on pre-Ampere GPUs that lack bf16. Otherwise prefer bf16.",
    },
    {
        "path": "training.gradient_checkpointing", "label": "Gradient checkpointing",
        "group": "Memory & speed", "essential": False, "type": "bool",
        "methods": ["sft", "dpo"],
        "help": (
            "Recomputes activations during the backward pass instead of storing "
            "them, trading roughly 20% speed for a large memory saving."
        ),
        "recommended": "On unless you have VRAM to spare. It is often what lets a model fit at all.",
    },
    {
        "path": "training.packing", "label": "Sequence packing",
        "group": "Memory & speed", "essential": False, "type": "bool",
        "methods": ["sft"],
        "help": (
            "Concatenates several short examples into each training sequence so "
            "little compute is wasted on padding. Big throughput win when your "
            "examples are short."
        ),
        "recommended": "On for short-example datasets. Off if examples already fill the sequence length.",
    },
    {
        "path": "training.use_liger_kernel", "label": "Liger kernels",
        "group": "Memory & speed", "essential": False, "type": "bool",
        "methods": ["sft", "dpo"],
        "help": (
            "Swaps in fused Triton kernels for common layers: roughly 60% less "
            "memory and 20% more throughput, with identical results. CUDA only."
        ),
        "recommended": "On when training on NVIDIA GPUs and the liger-kernel package is installed.",
    },
    {
        "path": "training.torch_compile", "label": "torch.compile",
        "group": "Memory & speed", "essential": False, "type": "bool",
        "methods": ["sft"],
        "help": (
            "Compiles the model graph for a speedup after a slow first step. "
            "Still experimental with PEFT/LoRA and can fail to compile."
        ),
        "recommended": "Leave off unless you have verified it works and speeds up your setup.",
    },
    # --- Loss & regularization -----------------------------------------------
    {
        "path": "training.loss_type", "label": "SFT loss", "group": "Loss & regularization",
        "essential": False, "type": "select",
        "options": ["nll", "dft", "chunked_nll"], "methods": ["sft"],
        "help": "The objective the SFT trainer optimizes.",
        "option_help": {
            "nll": "Standard cross-entropy (next-token prediction). The default.",
            "dft": "Dynamic Fine-Tuning with a rectified reward; can generalize better on some data.",
            "chunked_nll": "Same math as nll, computed in chunks for lower peak memory.",
        },
        "recommended": "nll. Use chunked_nll if the loss step runs you out of memory.",
    },
    {
        "path": "training.neftune_noise_alpha", "label": "NEFTune noise",
        "group": "Loss & regularization", "essential": False, "type": "float",
        "min": 0.0, "max": 15.0, "step": 0.5, "methods": ["sft"],
        "help": (
            "Adds a little noise to the input embeddings during training, a "
            "cheap trick that often improves how well the model generalizes."
        ),
        "recommended": "5 is the common setting. 0 disables it.",
    },
    {
        "path": "training.assistant_only_loss", "label": "Assistant-only loss",
        "group": "Loss & regularization", "essential": False, "type": "bool",
        "methods": ["sft"],
        "help": (
            "Trains only on the assistant's turns, not the user's, so the model "
            "learns to answer rather than to imitate prompts. Needs a chat "
            "template with generation markers."
        ),
        "recommended": "On for multi-turn chat data with a proper chat template.",
    },
    {
        "path": "training.completion_only_loss", "label": "Completion-only loss",
        "group": "Loss & regularization", "essential": False, "type": "bool",
        "methods": ["sft"],
        "help": (
            "For prompt/completion data, scores only the completion so the model "
            "is not penalized for the fixed prompt text."
        ),
        "recommended": "On for prompt/completion datasets.",
    },
    {
        "path": "dpo.beta", "label": "DPO beta", "group": "Loss & regularization",
        "essential": False, "type": "float", "min": 0.01, "max": 1.0,
        "step": 0.01, "methods": ["dpo"],
        "help": (
            "How strongly DPO pushes toward the chosen answer over the rejected "
            "one, while a lower value keeps the model closer to where it started."
        ),
        "recommended": "0.1 is a solid default. 0.05 to 0.1 is conservative; higher risks drifting off-distribution.",
    },
    {
        "path": "dpo.label_smoothing", "label": "Label smoothing",
        "group": "Loss & regularization", "essential": False, "type": "float",
        "min": 0.0, "max": 0.5, "step": 0.01, "methods": ["dpo"],
        "help": (
            "Assumes some preference labels are wrong (conservative/robust DPO), "
            "which prevents the model from trusting noisy pairs too much."
        ),
        "recommended": "0 for clean labels. 0.1 to 0.2 if your chosen/rejected pairs contain mistakes.",
    },
    # --- Run & tracking ---------------------------------------------------------
    {
        "path": "training.seed", "label": "Random seed", "group": "Run & tracking",
        "essential": False, "type": "int", "min": 0, "max": 2**31 - 1, "step": 1,
        "methods": ["sft", "dpo"],
        "help": (
            "Fixes the randomness in data shuffling and initialization so the "
            "same config reproduces the same run."
        ),
        "recommended": "Any fixed value (42 is traditional). Change it to average results across seeds.",
    },
    {
        "path": "training.logging_steps", "label": "Logging interval",
        "group": "Run & tracking", "essential": False, "type": "int",
        "min": 1, "max": 500, "step": 1, "methods": ["sft", "dpo"],
        "help": (
            "How many steps between logged metric points, which sets the "
            "resolution of the live loss curve."
        ),
        "recommended": "1 for short smoke runs; 10 to 50 for long runs to keep the log tidy.",
    },
    {
        "path": "training.report_to", "label": "Extra tracking sink",
        "group": "Run & tracking", "essential": False, "type": "select",
        "options": ["none", "tensorboard", "wandb", "mlflow", "comet_ml",
                    "clearml", "dvclive", "neptune"],
        "methods": ["sft", "dpo"],
        "help": (
            "Optionally mirror metrics to an external experiment tracker. "
            "Puffin's own run tracking and live curve work regardless."
        ),
        "recommended": "none unless your team already uses one of these trackers.",
    },
    {
        "path": "training.save_strategy", "label": "Checkpoint frequency",
        "group": "Run & tracking", "essential": False, "type": "select",
        "options": ["epoch", "steps", "no"], "methods": ["sft", "dpo"],
        "help": (
            "When to save a checkpoint you could resume or evaluate from during "
            "the run."
        ),
        "option_help": {
            "epoch": "Save once at the end of each epoch. Good default.",
            "steps": "Save every N steps (uses the framework's step interval).",
            "no": "Save nothing mid-run; keep only the final adapter.",
        },
        "recommended": "epoch for most runs. no for quick smoke tests.",
    },
    {
        "path": "training.save_total_limit", "label": "Checkpoints to keep",
        "group": "Run & tracking", "essential": False, "type": "int",
        "min": 1, "max": 20, "step": 1, "methods": ["sft", "dpo"],
        "help": (
            "The most checkpoints kept on disk at once; older ones are deleted "
            "past this cap so the disk does not fill up."
        ),
        "recommended": "2 to 3 is plenty. Lower it if disk space is tight.",
    },
    # --- KTO (unpaired preference) -------------------------------------------
    {
        "path": "kto.beta", "label": "KTO beta", "group": "Loss & regularization",
        "essential": True, "type": "float", "min": 0.01, "max": 1.0, "step": 0.01,
        "methods": ["kto"],
        "help": "How hard KTO pushes toward the desirable (thumbs-up) completions "
                "versus staying near the reference model.",
        "recommended": "0.1 (0.05-0.2 typical).",
    },
    {
        "path": "kto.desirable_weight", "label": "Desirable weight",
        "group": "Loss & regularization", "essential": False, "type": "float",
        "min": 0.1, "max": 10.0, "step": 0.1, "methods": ["kto"],
        "help": "Up-weights the thumbs-up examples in the loss. Raise it when "
                "negatives greatly outnumber positives.",
        "recommended": "1.0 unless your labels are imbalanced.",
    },
    {
        "path": "kto.undesirable_weight", "label": "Undesirable weight",
        "group": "Loss & regularization", "essential": False, "type": "float",
        "min": 0.1, "max": 10.0, "step": 0.1, "methods": ["kto"],
        "help": "Up-weights the thumbs-down examples. Raise it when positives "
                "dominate your data.",
        "recommended": "1.0 unless your labels are imbalanced.",
    },
    # --- GRPO (online RL) ----------------------------------------------------
    {
        "path": "grpo.num_generations", "label": "Generations per prompt",
        "group": "Loss & regularization", "essential": True, "type": "int",
        "min": 2, "max": 16, "step": 1, "methods": ["grpo"],
        "help": "How many completions the model samples per prompt to compare "
                "against each other. Must divide batch x gradient accumulation.",
        "recommended": "4 to 8. More gives a cleaner signal but is slower.",
    },
    {
        "path": "grpo.max_completion_length", "label": "Max completion length",
        "group": "Loss & regularization", "essential": False, "type": "int",
        "min": 16, "max": 2048, "step": 16, "methods": ["grpo"],
        "help": "Token budget for each sampled completion during RL.",
        "recommended": "128 to 256 for chat; longer costs more per step.",
    },
    {
        "path": "grpo.temperature", "label": "Sampling temperature",
        "group": "Loss & regularization", "essential": False, "type": "float",
        "min": 0.1, "max": 2.0, "step": 0.1, "methods": ["grpo"],
        "help": "Randomness of the sampled completions. Higher explores more.",
        "recommended": "0.7 to 1.0.",
    },
    # --- RLOO (online RL) ----------------------------------------------------
    {
        "path": "rloo.num_generations", "label": "Generations per prompt",
        "group": "Loss & regularization", "essential": True, "type": "int",
        "min": 2, "max": 16, "step": 1, "methods": ["rloo"],
        "help": "Group size sampled per prompt; the leave-one-out baseline is the "
                "mean reward of the others. Must divide batch x gradient accumulation.",
        "recommended": "4.",
    },
    {
        "path": "rloo.max_completion_length", "label": "Max completion length",
        "group": "Loss & regularization", "essential": False, "type": "int",
        "min": 16, "max": 2048, "step": 16, "methods": ["rloo"],
        "help": "Token budget for each sampled completion during RL.",
        "recommended": "128 to 256.",
    },
    {
        "path": "rloo.kl_coef", "label": "KL penalty", "group": "Loss & regularization",
        "essential": False, "type": "float", "min": 0.0, "max": 1.0, "step": 0.01,
        "methods": ["rloo"],
        "help": "Keeps the policy from drifting too far from the reference model.",
        "recommended": "0.03 to 0.1.",
    },
    # --- Built-in reward (GRPO/RLOO) -----------------------------------------
    {
        "path": "reward.target_chars", "label": "Reward target length",
        "group": "Loss & regularization", "essential": False, "type": "int",
        "min": 20, "max": 2000, "step": 10, "methods": ["grpo", "rloo"],
        "help": "The built-in reward peaks at this answer length (characters). "
                "Only used by the default reward; ignored once you wire a real "
                "reward model or function.",
        "recommended": "Set it near your ideal answer length.",
    },
]

# Shared knobs (model / LoRA / schedule / optimizer / tracking) declare
# methods ["sft","dpo"]; extend them to every method so the new trainers get
# the same surface without repeating the list on ~30 knobs. SFT-only text
# knobs and the preference/RL loss knobs keep their narrower lists.
for _k in KNOBS:
    if _k["methods"] == ["sft", "dpo"]:
        _k["methods"] = list(ALL_METHODS)

KNOBS_BY_PATH: dict[str, dict[str, Any]] = {k["path"]: k for k in KNOBS}

GROUP_ORDER = [
    "Model", "Data", "LoRA / PEFT", "Training schedule", "Optimizer",
    "Memory & speed", "Loss & regularization", "Run & tracking",
]

# Virtual selects — friendly option name → actual config value.
_QUANT_PRESETS: dict[str, Any] = {
    "none": None,
    "qlora-nf4": {
        "backend": "bitsandbytes",
        "load_in_4bit": True,
        "load_in_8bit": False,
        "bnb_4bit_quant_type": "nf4",
        "bnb_4bit_compute_dtype": "bfloat16",
        "bnb_4bit_use_double_quant": True,
    },
    "int8": {
        "backend": "bitsandbytes",
        "load_in_4bit": False,
        "load_in_8bit": True,
    },
}
_TARGET_PRESETS: dict[str, list[str]] = {
    "attention": ["q_proj", "k_proj", "v_proj", "o_proj"],
    "all-linear": ["q_proj", "k_proj", "v_proj", "o_proj",
                   "gate_proj", "up_proj", "down_proj"],
}
_VIRTUAL = {"model.quantization": _QUANT_PRESETS,
            "lora.target_modules": _TARGET_PRESETS}


# ---------------------------------------------------------------------------
# Dotted-path helpers
# ---------------------------------------------------------------------------
def _get_dotted(cfg: dict[str, Any], path: str) -> Any:
    node: Any = cfg
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _set_dotted(cfg: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    node = cfg
    for part in parts[:-1]:
        nxt = node.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            node[part] = nxt
        node = nxt
    node[parts[-1]] = value


def _reverse_virtual(path: str, raw: Any) -> Any:
    """Map an actual config value back to the friendly option name."""
    if path == "model.quantization":
        if not isinstance(raw, dict):
            return "none"
        if raw.get("load_in_4bit"):
            return "qlora-nf4"
        if raw.get("load_in_8bit"):
            return "int8"
        return "none"
    if path == "lora.target_modules":
        mods = set(raw or [])
        return "all-linear" if "gate_proj" in mods else "attention"
    return raw


def _coerce(knob: dict[str, Any], value: Any) -> Any:
    """Type-check one override value against its knob. Raises StudioError."""
    t = knob["type"]
    try:
        if t == "bool":
            if isinstance(value, bool):
                return value
            raise TypeError
        if t == "int":
            if isinstance(value, bool):
                raise TypeError
            return int(value)
        if t == "float":
            if isinstance(value, bool):
                raise TypeError
            return float(value)
        if t == "select":
            v = str(value)
            if v not in knob["options"]:
                raise TypeError
            return v
        return str(value)
    except (TypeError, ValueError):
        raise StudioError(
            f"invalid value for {knob['path']!r}: {value!r} "
            f"(expected {t}{' one of ' + str(knob['options']) if t == 'select' else ''})"
        ) from None


def validate_overrides(
    overrides: dict[str, Any], *, method: str,
) -> dict[str, Any]:
    """Check paths + types against the knob schema; translate virtual
    selects to real config values. Returns the translated dict."""
    out: dict[str, Any] = {}
    for path, value in (overrides or {}).items():
        knob = KNOBS_BY_PATH.get(path)
        if knob is None:
            raise StudioError(f"unknown knob: {path!r}")
        if method not in knob["methods"]:
            raise StudioError(f"knob {path!r} does not apply to method {method!r}")
        coerced = _coerce(knob, value)
        if path in _VIRTUAL:
            out[path] = copy.deepcopy(_VIRTUAL[path][coerced])
        else:
            out[path] = coerced
    return out


# ---------------------------------------------------------------------------
# Catalog + materialization
# ---------------------------------------------------------------------------
def studio_catalog(repo_root: Path) -> dict[str, Any]:
    """Everything the /train page needs: recipes, knobs, current values."""
    current: dict[str, dict[str, Any]] = {}
    for method, rel in BASE_CONFIG.items():
        p = repo_root / rel
        try:
            cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            cfg = {}
        vals: dict[str, Any] = {}
        for knob in KNOBS:
            if method not in knob["methods"]:
                continue
            raw = _get_dotted(cfg, knob["path"])
            vals[knob["path"]] = (
                _reverse_virtual(knob["path"], raw)
                if knob["path"] in _VIRTUAL else raw
            )
        current[method] = vals
    custom = load_custom_recipes(repo_root)
    categories = list(RECIPE_CATEGORIES)
    if custom:
        categories = [CUSTOM_CATEGORY, *categories]  # user's presets first
    return {
        "recipes": [*custom, *RECIPES],
        "recipe_categories": categories,
        "knobs": KNOBS,
        "group_order": GROUP_ORDER,
        "current": current,
        "base_config": BASE_CONFIG,
        "studio_config": STUDIO_CONFIG,
        "cloud_targets": CLOUD_TARGETS,
    }


def materialize(
    repo_root: Path,
    *,
    method: str,
    recipe_id: str | None = None,
    overrides: dict[str, Any] | None = None,
    write: bool = True,
) -> tuple[str, str]:
    """Merge recipe + user overrides into the base config and (optionally)
    write the studio config file. Returns (rel_path, yaml_text)."""
    if method not in BASE_CONFIG:
        raise StudioError(f"method must be one of {sorted(BASE_CONFIG)}")

    recipe = None
    if recipe_id:
        recipe = next(
            (r for r in _all_recipes(repo_root) if r["id"] == recipe_id), None)
        if recipe is None:
            raise StudioError(f"unknown recipe: {recipe_id!r}")
        if recipe["method"] != method:
            raise StudioError(
                f"recipe {recipe_id!r} is a {recipe['method']} recipe, "
                f"not {method}")

    # User overrides win over recipe overrides.
    merged_raw: dict[str, Any] = {}
    if recipe:
        merged_raw.update(recipe["overrides"])
    merged_raw.update(overrides or {})
    translated = validate_overrides(merged_raw, method=method)

    base_rel = BASE_CONFIG[method]
    base_path = repo_root / base_rel
    if not base_path.exists():
        raise StudioError(f"base config not found: {base_rel}")
    cfg = yaml.safe_load(base_path.read_text(encoding="utf-8")) or {}
    for path, value in translated.items():
        _set_dotted(cfg, path, value)

    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    header = (
        "# ── Generated by Puffin Train Studio ─────────────────────────\n"
        f"# Base:    {base_rel}\n"
        f"# Recipe:  {recipe_id or '(custom)'}\n"
        f"# Written: {ts}\n"
        "# Overwritten on every studio launch — do not hand-edit.\n"
        "# For permanent defaults edit the base config instead.\n"
    )
    text = header + yaml.safe_dump(
        cfg, sort_keys=False, allow_unicode=True, default_flow_style=False)

    rel = STUDIO_CONFIG[method]
    if write:
        (repo_root / rel).write_text(text, encoding="utf-8")
    return rel, text
