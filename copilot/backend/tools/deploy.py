"""Deploy tools — push to registry, promote between aliases, render k8s manifest."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from copilot.backend.tools.registry import ToolContext, ToolError, tool


class DeployPushArgs(BaseModel):
    name: str = Field(description="Model name in the registry (default lives in configs/deploy.yaml model.name).")
    adapter_dir: str = Field(
        default="artifacts/adapter",
        description="Path to the adapter directory to push (relative to repo).",
    )
    alias: str = Field(
        default="candidate",
        description="Initial alias to assign. One of: candidate, staging, production, archived.",
    )


@tool(
    "deploy_push",
    description=(
        "Push an adapter to the local model registry as a new version. Returns "
        "the URI and assigned version number."
    ),
    args_model=DeployPushArgs,
    dangerous=True,
)
async def deploy_push(args: DeployPushArgs, ctx: ToolContext) -> dict[str, Any]:
    adapter = (ctx.repo_root / args.adapter_dir).resolve()
    if not str(adapter).startswith(str(ctx.repo_root)):
        raise ToolError("adapter_dir escapes repo root")
    if not adapter.exists():
        raise ToolError(f"adapter not found: {args.adapter_dir}")

    # Use the same code path the CLI does — local provider, in-process.
    from llmops.providers.local import LocalRegistry
    reg = LocalRegistry(root=str(ctx.repo_root / "artifacts"))
    try:
        uri = reg.register_model(adapter, name=args.name)
    except Exception as exc:  # noqa: BLE001
        raise ToolError(f"push failed: {type(exc).__name__}: {exc}") from exc

    # If an alias was requested, promote in the same call.
    promoted = False
    if args.alias and args.alias != "candidate":
        # Parse the version from the URI tail
        version = uri.rsplit("/", 1)[-1]
        try:
            reg.promote(name=args.name, version=version, alias=args.alias)
            promoted = True
        except Exception as exc:  # noqa: BLE001
            return {
                "kind": "deploy_push_result",
                "uri": uri,
                "alias_set": False,
                "warning": f"pushed v{version} but alias {args.alias!r} not set: {exc}",
            }

    return {
        "kind": "deploy_push_result",
        "uri": uri,
        "alias_set": promoted,
        "alias": args.alias if promoted else "candidate",
        "name": args.name,
    }


class DeployPromoteArgs(BaseModel):
    name: str
    version: str = Field(description="Version string, e.g. '1' or 'v1'.")
    alias: str = Field(description="One of: candidate, staging, production, archived.")


@tool(
    "deploy_promote",
    description=(
        "Move an alias pointer to a specific version (rollback = re-point). "
        "Aliases: candidate → staging → production → archived."
    ),
    args_model=DeployPromoteArgs,
    dangerous=True,
)
async def deploy_promote(args: DeployPromoteArgs, ctx: ToolContext) -> dict[str, Any]:
    from llmops.providers.local import LocalRegistry
    reg = LocalRegistry(root=str(ctx.repo_root / "artifacts"))
    try:
        reg.promote(name=args.name, version=str(args.version).lstrip("v"),
                    alias=args.alias)
    except Exception as exc:  # noqa: BLE001
        raise ToolError(f"promote failed: {type(exc).__name__}: {exc}") from exc
    return {
        "kind": "deploy_promote_result",
        "name": args.name, "version": args.version, "alias": args.alias,
        "message": f"{args.name} v{args.version} → {args.alias}",
    }


class K8sManifestArgs(BaseModel):
    environment: str = Field(default="staging")
    replicas: int = Field(default=2, ge=1, le=100)
    gpu: bool = False
    namespace: str = Field(default="puffin")
    model_ref: str = Field(default="puffin:latest")
    serving_image: str = Field(default="puffin-serve:latest")


@tool(
    "deploy_render_k8s",
    description=(
        "Render the Kubernetes manifest (deployment + service + HPA) that would "
        "deploy serving. Read-only — does not apply anything."
    ),
    args_model=K8sManifestArgs,
)
async def deploy_render_k8s(args: K8sManifestArgs, ctx: ToolContext) -> dict[str, Any]:
    from llmops.providers.kubernetes import K8sDeployment
    yaml_text = K8sDeployment(
        namespace=args.namespace, serving_image=args.serving_image,
    ).render(
        model_ref=args.model_ref, environment=args.environment,
        replicas=args.replicas, gpu=args.gpu,
    )
    return {
        "kind": "k8s_manifest",
        "yaml": yaml_text,
        "lines": yaml_text.count("\n") + 1,
        "bytes": len(yaml_text.encode("utf-8")),
        "args": args.model_dump(),
    }
