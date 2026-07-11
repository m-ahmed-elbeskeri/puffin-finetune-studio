"""Tool registry + implementations exposed to the LLM via tool-use.

Every tool is a typed function:

    @register
    async def project_status(args: ProjectStatusArgs, ctx: ToolContext) -> dict:
        ...

Args are Pydantic models so we get JSON-schema generation for free, and
runtime validation when the model produces tool calls.

Return values are JSON-serialisable dicts; each has a `kind` key that the
frontend's artifact router uses to pick a render component
(e.g. `kind="run_card"` → `<RunCard />`).
"""
from copilot.backend.tools.registry import (
    ToolContext,
    ToolDefinition,
    registry,
    tool,
)

# Importing modules registers their tools (side-effect decorators).
from copilot.backend.tools import (  # noqa: F401, E402
    configs as _configs,
    data as _data,
    deploy as _deploy,
    eval as _eval,
    interaction as _interaction,
    monitor as _monitor,
    project as _project,
    registry_models as _registry_models,
    serve as _serve,
    studio as _studio,
    train as _train,
)

__all__ = ["ToolContext", "ToolDefinition", "registry", "tool"]
