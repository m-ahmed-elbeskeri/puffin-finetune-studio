"""Train Studio tools — give the AI the same powers as the /train page.

`train_studio_recipes` lists the curated recipes + tunable knobs so the
model can reason about options; `train_studio_launch` materializes a config
from a recipe and/or knob overrides and starts the run through train_start
(same subprocess, sidecars, and gating as every other launch path).
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from copilot.backend.tools.registry import ToolContext, ToolError, tool
from copilot.backend.training_studio import (
    KNOBS,
    RECIPES,
    StudioError,
    materialize,
    studio_catalog,
)


class _Empty(BaseModel):
    pass


@tool(
    "train_studio_recipes",
    description=(
        "List the Train Studio's curated training recipes (smoke-test, "
        "style-tune, domain-adapt, qlora-single-gpu, full-finetune, "
        "dpo-align) and every tunable knob with its current value from the "
        "base config. Call this before train_studio_launch to pick a recipe "
        "or valid knob paths, or when the user asks what training options "
        "exist."
    ),
    args_model=_Empty,
)
async def train_studio_recipes(args: _Empty, ctx: ToolContext) -> dict[str, Any]:
    cat = studio_catalog(ctx.repo_root)
    return {
        "kind": "studio_catalog",
        "recipes": [
            {k: r[k] for k in
             ("id", "label", "category", "method", "tagline", "overrides",
              "needs_gpu", "est_time")}
            for r in RECIPES
        ],
        "knobs": [
            {k: v for k, v in knob.items() if k != "help"}
            for knob in KNOBS
        ],
        "current": cat["current"],
    }


class StudioLaunchArgs(BaseModel):
    recipe: str | None = Field(
        default=None,
        description=(
            "Recipe id from train_studio_recipes (e.g. 'style-tune'). "
            "Optional — omit for a pure knob-override launch."
        ),
    )
    method: str = Field(
        default="sft", description="'sft' or 'dpo'. Must match the recipe if one is given.",
    )
    smoke: bool = Field(
        default=True,
        description="Smoke test first (tiny model, ~1 min). ALWAYS true for "
                    "a first run on a new dataset/config.",
    )
    overrides: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Dotted knob-path overrides, e.g. {'lora.r': 32, "
            "'training.learning_rate': 1e-4, 'model.quantization': "
            "'qlora-nf4'}. Validated against the knob schema; user "
            "overrides beat recipe values."
        ),
    )


@tool(
    "train_studio_launch",
    description=(
        "Launch training via the Train Studio: applies a curated recipe "
        "and/or knob overrides on top of the base config (writing "
        "configs/train_studio.yaml — the base config is never modified) "
        "and starts the run. Prefer this over train_start + config_edit "
        "when the user asks to train with specific settings."
    ),
    args_model=StudioLaunchArgs,
    dangerous=True,
)
async def train_studio_launch(
    args: StudioLaunchArgs, ctx: ToolContext,
) -> dict[str, Any]:
    from copilot.backend.tools.registry import registry

    method = args.method.lower()
    try:
        rel, _text = materialize(
            ctx.repo_root, method=method,
            recipe_id=args.recipe, overrides=args.overrides,
        )
    except StudioError as exc:
        raise ToolError(str(exc)) from exc
    result = await registry.invoke(
        "train_start", {"method": method, "smoke": args.smoke, "config": rel},
        ctx)
    if result.get("kind") == "train_started":
        result["config_path"] = rel
        result["recipe"] = args.recipe
        result["overrides"] = args.overrides
    return result
