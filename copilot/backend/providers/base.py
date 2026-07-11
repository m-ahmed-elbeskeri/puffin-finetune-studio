"""Provider interface — what the tool-use loop calls into.

A Provider runs ONE assistant turn against a list of input messages +
the registered tools, streaming events back to the caller.

Stream protocol (yielded events):
    {"type": "text_delta", "text": "..."}
    {"type": "tool_use_start", "id": "...", "name": "...", "input_partial": ""}
    {"type": "tool_use_delta", "id": "...", "input_partial": "..."}
    {"type": "tool_use_end", "id": "...", "name": "...", "input": {...}}
    {"type": "turn_end", "stop_reason": "end_turn" | "tool_use" | "max_tokens",
     "usage": {"input_tokens": int, "output_tokens": int},
     "content": [...]   # full content list — what to persist in the message log}
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncIterator, Protocol


StreamEvent = dict[str, Any]


@dataclass
class AssistantTurn:
    """Captured at end of a turn. The loop persists `content` to the thread."""
    stop_reason: str
    content: list[dict[str, Any]]
    input_tokens: int
    output_tokens: int


class AssistantEvent:
    """Type tags for the SSE envelope sent to the frontend. Stringy so we
    can render them in tests without importing the producer."""
    TEXT = "text"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    USAGE = "usage"
    DONE = "done"
    ERROR = "error"


class Provider(Protocol):
    """Abstract chat provider. Each call streams one assistant turn."""

    name: str

    async def stream_turn(
        self,
        *,
        model: str,
        system: str | None,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
        tool_ctx: Any = None,
    ) -> AsyncIterator[StreamEvent]:
        """Stream events for one assistant turn. Yields StreamEvents. The
        final event MUST have type='turn_end'.

        `tool_ctx` is the per-request ToolContext (carries the project the
        chat thread belongs to). Providers that run tools themselves (Claude
        Code MCP, the agent CLIs) MUST scope to `tool_ctx.repo_root` when it
        is given, otherwise they operate on the wrong project."""
        ...
