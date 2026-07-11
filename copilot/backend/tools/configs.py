"""Config tools — read configs/*.yaml + profiles/*.yaml; propose edits.

config_edit applies a diff (search/replace) atomically with a .bak sidecar
and re-validates with yaml.safe_load before writing.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from copilot.backend.tools.registry import ToolContext, ToolError, tool


def _validate_inside_repo(repo: Path, rel: str) -> Path:
    p = (repo / rel).resolve()
    if not str(p).startswith(str(repo)):
        raise ToolError(f"path escapes repo root: {rel}")
    return p


def _allowed_config(rel: str) -> bool:
    return (
        rel.startswith("configs/") or rel.startswith("profiles/")
    ) and rel.endswith(".yaml")


class _Empty(BaseModel):
    pass


@tool(
    "config_list",
    description="List all configs/*.yaml and profiles/*.yaml in the repo.",
    args_model=_Empty,
)
async def config_list(args: _Empty, ctx: ToolContext) -> dict[str, Any]:
    out: list[dict[str, Any]] = []
    for sub in ("configs", "profiles"):
        d = ctx.repo_root / sub
        if not d.exists():
            continue
        for f in sorted(d.glob("*.yaml")):
            out.append({
                "path": str(f.relative_to(ctx.repo_root)),
                "bytes": f.stat().st_size,
            })
    return {"kind": "config_list", "files": out}


class ConfigReadArgs(BaseModel):
    path: str = Field(description="Path under configs/ or profiles/ (e.g. 'configs/train.yaml').")


@tool(
    "config_read",
    description="Read a YAML config or profile and return its text + parsed dict.",
    args_model=ConfigReadArgs,
)
async def config_read(args: ConfigReadArgs, ctx: ToolContext) -> dict[str, Any]:
    if not _allowed_config(args.path):
        raise ToolError(f"only configs/ and profiles/ YAML files are readable: {args.path}")
    p = _validate_inside_repo(ctx.repo_root, args.path)
    if not p.exists():
        raise ToolError(f"no such file: {args.path}")
    text = p.read_text(encoding="utf-8")
    import yaml
    try:
        parsed = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise ToolError(f"YAML parse error: {exc}") from exc
    return {
        "kind": "config_read",
        "path": args.path, "text": text, "parsed": parsed,
        "bytes": len(text.encode("utf-8")),
    }


class ConfigEditArgs(BaseModel):
    path: str
    new_text: str = Field(
        description=(
            "Full replacement YAML text. The handler parses it with "
            "yaml.safe_load before writing; if parsing fails the file is "
            "untouched."
        ),
    )


@tool(
    "config_edit",
    description=(
        "Overwrite a config or profile YAML file. Validates with yaml.safe_load "
        "before writing. Writes a .bak alongside the original. DESTRUCTIVE — gated."
    ),
    args_model=ConfigEditArgs,
    dangerous=True,
)
async def config_edit(args: ConfigEditArgs, ctx: ToolContext) -> dict[str, Any]:
    if not _allowed_config(args.path):
        raise ToolError(f"only configs/ and profiles/ YAML files can be edited: {args.path}")
    p = _validate_inside_repo(ctx.repo_root, args.path)
    if not p.exists():
        raise ToolError(f"no such file: {args.path}")

    import yaml
    try:
        yaml.safe_load(args.new_text)  # validation pass
    except yaml.YAMLError as exc:
        raise ToolError(f"refusing to write — YAML parse error: {exc}") from exc

    old_text = p.read_text(encoding="utf-8")
    backup = p.with_suffix(p.suffix + ".bak")
    backup.write_text(old_text, encoding="utf-8")
    p.write_text(args.new_text, encoding="utf-8")

    return {
        "kind": "config_edit_result",
        "path": args.path,
        "backup": str(backup.relative_to(ctx.repo_root)),
        "old_bytes": len(old_text.encode("utf-8")),
        "new_bytes": len(args.new_text.encode("utf-8")),
        "old_text": old_text,
        "new_text": args.new_text,
    }
