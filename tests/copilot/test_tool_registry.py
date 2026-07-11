"""Registry-level tests: schema gen, validation, dangerous-tool gating."""

from __future__ import annotations

from pathlib import Path

import pytest
from copilot.backend.tools.registry import (
    ToolContext,
    ToolDefinition,
    _Registry,
)
from pydantic import BaseModel


def test_global_registry_loaded():
    from copilot.backend.tools import registry

    names = {t.name for t in registry.all()}
    # Spot-check the workflow-spanning tools that the loop relies on.
    expected = {
        "project_status",
        "dataset_audit",
        "data_pipeline_run",
        "train_start",
        "train_status",
        "train_history",
        "train_get_run",
        "train_cancel",
        "eval_run",
        "gate_apply",
        "eval_get_metrics",
        "deploy_push",
        "deploy_promote",
        "deploy_render_k8s",
        "registry_list",
        "serve_health",
        "serve_chat",
        "monitor_request_log",
        "monitor_quality",
        "monitor_drift",
        "config_list",
        "config_read",
        "config_edit",
    }
    missing = expected - names
    assert not missing, f"missing tools: {missing}"


def test_anthropic_schemas_well_formed():
    from copilot.backend.tools import registry

    schemas = registry.to_anthropic_schemas()
    for s in schemas:
        assert "name" in s and "description" in s and "input_schema" in s
        assert s["input_schema"].get("type") == "object"


@pytest.mark.asyncio
async def test_invoke_unknown_tool_returns_error():
    from copilot.backend.tools import registry

    ctx = ToolContext(repo_root=__import__("pathlib").Path("."))
    r = await registry.invoke("does_not_exist", {}, ctx)
    assert r["kind"] == "error"
    assert "Unknown tool" in r["message"]


@pytest.mark.asyncio
async def test_invoke_bad_args_returns_validation_error():
    from copilot.backend.tools import registry

    # dataset_audit requires `path` (no default).
    ctx = ToolContext(repo_root=__import__("pathlib").Path("."))
    r = await registry.invoke("dataset_audit", {}, ctx)
    assert r["kind"] == "error"
    assert "Bad arguments" in r["message"]


@pytest.mark.asyncio
async def test_dangerous_tool_blocked_when_disabled():
    class A(BaseModel):
        x: int = 1

    async def handler(args, ctx):
        return {"kind": "ok"}

    local_reg = _Registry()
    local_reg.register(
        ToolDefinition(
            name="dangerous_thing",
            description="...",
            args_model=A,
            handler=handler,
            dangerous=True,
        )
    )

    blocked = await local_reg.invoke(
        "dangerous_thing",
        {"x": 1},
        ToolContext(repo_root=Path("."), enable_dangerous=False),
    )
    assert blocked["kind"] == "error"
    assert "disabled" in blocked["message"].lower()

    allowed = await local_reg.invoke(
        "dangerous_thing",
        {"x": 1},
        ToolContext(repo_root=Path("."), enable_dangerous=True),
    )
    assert allowed["kind"] == "ok"


@pytest.mark.asyncio
async def test_handler_exception_is_captured_not_raised():
    class A(BaseModel):
        pass

    async def boom(args, ctx):
        raise RuntimeError("kaboom")

    local_reg = _Registry()
    local_reg.register(
        ToolDefinition(
            name="boom",
            description="...",
            args_model=A,
            handler=boom,
        )
    )
    r = await local_reg.invoke("boom", {}, ToolContext(repo_root=Path(".")))
    assert r["kind"] == "error"
    assert "kaboom" in r["message"]
