"""Registry tools — list local registry contents."""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from copilot.backend.tools.registry import ToolContext, tool


class _Empty(BaseModel):
    pass


@tool(
    "registry_list",
    description=(
        "List models in the local registry with their versions + alias "
        "assignments (candidate / staging / production / archived)."
    ),
    args_model=_Empty,
)
async def registry_list(args: _Empty, ctx: ToolContext) -> dict[str, Any]:
    root = ctx.repo_root / "artifacts" / "_registry"
    models: list[dict[str, Any]] = []
    if root.exists():
        for model_dir in sorted(p for p in root.iterdir() if p.is_dir()):
            manifest_path = model_dir / "manifest.json"
            if not manifest_path.exists():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            models.append({
                "name": model_dir.name,
                "versions": [
                    {
                        "version": v.get("version"),
                        "registered_at": v.get("registered_at"),
                        "metrics": v.get("metrics", {}),
                        "tags": v.get("tags", {}),
                    }
                    for v in manifest.get("versions", [])
                ],
                "aliases": manifest.get("aliases", {}),
            })
    return {"kind": "registry", "models": models}
