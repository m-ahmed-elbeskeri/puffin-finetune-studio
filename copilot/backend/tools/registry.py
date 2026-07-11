"""Decorator-based tool registry.

Each tool is a coroutine that takes a Pydantic args model and a
ToolContext, and returns a JSON-serialisable dict (or raises ToolError).

The registry produces:
  - `to_anthropic_schemas()` — list[dict] formatted for the Anthropic API
  - `invoke(name, raw_args, ctx)` — validates + dispatches, with safe error
    capture so a bad model output never kills the loop.
"""
from __future__ import annotations

import inspect
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, ValidationError


class ToolError(Exception):
    """Tools raise this to surface a user-visible error message."""
    pass


@dataclass(frozen=True)
class ToolContext:
    """Per-invocation context. Tests pass a fresh one; the app reuses a
    long-lived one bound to repo_root + a logger."""

    repo_root: Path
    enable_dangerous: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolDefinition:
    name: str
    description: str
    args_model: type[BaseModel]
    handler: Callable[[BaseModel, ToolContext], Awaitable[dict[str, Any]]]
    dangerous: bool = False
    """True for state-mutating tools — gated by ctx.enable_dangerous in prod."""

    def schema(self) -> dict[str, Any]:
        """Anthropic tool definition: {name, description, input_schema}."""
        schema = self.args_model.model_json_schema()
        # Anthropic doesn't accept $defs at the top level — inline refs if any.
        schema.pop("title", None)
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": schema,
        }


class _Registry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, td: ToolDefinition) -> None:
        if td.name in self._tools:
            raise ValueError(f"tool {td.name!r} already registered")
        self._tools[td.name] = td

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __getitem__(self, name: str) -> ToolDefinition:
        return self._tools[name]

    def all(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def to_anthropic_schemas(self) -> list[dict[str, Any]]:
        return [t.schema() for t in self._tools.values()]

    async def invoke(
        self,
        name: str,
        raw_args: dict[str, Any] | None,
        ctx: ToolContext,
    ) -> dict[str, Any]:
        """Validate + dispatch. Always returns a dict (never raises)."""
        td = self._tools.get(name)
        if td is None:
            return {
                "kind": "error",
                "tool": name,
                "message": f"Unknown tool: {name!r}.",
            }
        if td.dangerous and not ctx.enable_dangerous:
            return {
                "kind": "error",
                "tool": name,
                "message": (
                    f"Tool {name!r} is destructive and disabled. "
                    "Set PUFFIN_COPILOT_ENABLE_DANGEROUS=1 to permit."
                ),
            }
        try:
            args = td.args_model.model_validate(raw_args or {})
        except ValidationError as exc:
            return {
                "kind": "error",
                "tool": name,
                "message": f"Bad arguments: {exc.errors()}",
            }
        try:
            result = await td.handler(args, ctx)
            if not isinstance(result, dict):
                result = {"kind": "raw", "value": result}
            # Belt-and-braces: confirm the result is JSON-serialisable.
            json.dumps(result, default=str)
            return result
        except ToolError as exc:
            return {"kind": "error", "tool": name, "message": str(exc)}
        except Exception as exc:  # noqa: BLE001
            return {
                "kind": "error",
                "tool": name,
                "message": f"{type(exc).__name__}: {exc}",
            }


registry = _Registry()


def tool(
    name: str,
    *,
    description: str,
    args_model: type[BaseModel],
    dangerous: bool = False,
) -> Callable[
    [Callable[[BaseModel, ToolContext], Awaitable[dict[str, Any]]]],
    Callable[[BaseModel, ToolContext], Awaitable[dict[str, Any]]],
]:
    """Decorator that registers a coroutine as a tool.

    Example:

        class FooArgs(BaseModel):
            n: int = 1

        @tool("foo", description="...", args_model=FooArgs)
        async def foo(args: FooArgs, ctx: ToolContext) -> dict:
            return {"kind": "foo_result", "n": args.n}
    """
    def decorator(fn):
        if not inspect.iscoroutinefunction(fn):
            raise TypeError(f"tool {name!r} must be async (declared as 'async def').")
        registry.register(ToolDefinition(
            name=name,
            description=description,
            args_model=args_model,
            handler=fn,
            dangerous=dangerous,
        ))
        return fn
    return decorator
