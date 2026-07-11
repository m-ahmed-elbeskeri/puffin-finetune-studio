"""End-to-end tool-use loop with a stub provider.

The stub returns a scripted sequence of provider event streams (the second
stream is what the model emits after seeing the first tool_result), letting
us verify:
  - text deltas flow through
  - tool_use_end triggers tool invocation
  - tool_result is appended back to the conversation
  - the loop terminates on stop_reason='end_turn'
  - max_iterations guards against runaway loops
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, AsyncIterator

import pytest

from copilot.backend.loop import run_loop
from copilot.backend.tools import ToolContext


pytestmark = pytest.mark.asyncio


class StubProvider:
    """Scripted provider: each call to stream_turn pops a script entry."""

    name = "stub"

    def __init__(self, scripts: list[list[dict[str, Any]]]) -> None:
        self._scripts = list(scripts)
        self.calls: list[dict[str, Any]] = []

    async def stream_turn(self, **kwargs) -> AsyncIterator[dict[str, Any]]:
        self.calls.append(kwargs)
        if not self._scripts:
            raise AssertionError("no more scripted turns")
        script = self._scripts.pop(0)
        for evt in script:
            yield evt


async def _collect(stream) -> list[dict[str, Any]]:
    return [evt async for evt in stream]


async def test_loop_passes_tool_ctx_to_provider(tmp_path):
    """The provider MUST receive the per-request tool_ctx so tool-running
    providers (Claude Code MCP, agent CLIs) scope to the chat's project.
    Regression guard for the cross-project config-edit bug."""
    prov = StubProvider(scripts=[[
        {"type": "turn_end", "stop_reason": "end_turn",
         "usage": {"input_tokens": 1, "output_tokens": 1},
         "content": [{"type": "text", "text": "ok"}]},
    ]])
    ctx = ToolContext(repo_root=tmp_path, enable_dangerous=True)
    await _collect(run_loop(
        provider=prov, model="m", system="s",
        messages=[{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
        tool_ctx=ctx, max_tokens=10,
    ))
    assert prov.calls[0]["tool_ctx"] is ctx


async def test_loop_text_only_terminates_immediately(tmp_path):
    """No tool_use → loop runs ONE provider turn and exits."""
    prov = StubProvider(scripts=[[
        {"type": "text_delta", "text": "Hi"},
        {"type": "text_delta", "text": " there"},
        {"type": "turn_end", "stop_reason": "end_turn",
         "usage": {"input_tokens": 5, "output_tokens": 2},
         "content": [{"type": "text", "text": "Hi there"}]},
    ]])

    messages = [{"role": "user", "content": [
        {"type": "text", "text": "hello"}]}]
    ctx = ToolContext(repo_root=tmp_path, enable_dangerous=True)

    events = await _collect(run_loop(
        provider=prov, model="claude-test", system="sys",
        messages=messages, tool_ctx=ctx, max_tokens=100,
    ))
    types = [e["event"] for e in events]
    assert types.count("text") == 2
    assert "assistant_message" in types
    assert "usage" in types
    assert types[-1] == "done"
    # Provider was called exactly once.
    assert len(prov.calls) == 1
    # Final messages list grew by the assistant turn only.
    assert len(messages) == 2
    assert messages[-1]["role"] == "assistant"


async def test_loop_invokes_tool_then_completes(tmp_path):
    """tool_use in turn 1 → tool_result → text-only turn 2 → done."""
    # Seed the file project_status will read.
    (tmp_path / "data" / "raw").mkdir(parents=True)
    (tmp_path / "data" / "processed").mkdir(parents=True)
    (tmp_path / "artifacts" / "_registry").mkdir(parents=True)

    prov = StubProvider(scripts=[
        # Turn 1: assistant asks to call project_status
        [
            {"type": "tool_use_start", "id": "tu_1", "name": "project_status"},
            {"type": "tool_use_end", "id": "tu_1", "name": "project_status",
             "input": {}},
            {"type": "turn_end", "stop_reason": "tool_use",
             "usage": {"input_tokens": 10, "output_tokens": 3},
             "content": [{"type": "tool_use", "id": "tu_1",
                          "name": "project_status", "input": {}}]},
        ],
        # Turn 2: assistant comments on the result and stops
        [
            {"type": "text_delta", "text": "Looks empty."},
            {"type": "turn_end", "stop_reason": "end_turn",
             "usage": {"input_tokens": 20, "output_tokens": 2},
             "content": [{"type": "text", "text": "Looks empty."}]},
        ],
    ])
    messages = [{"role": "user", "content": [
        {"type": "text", "text": "status?"}]}]
    ctx = ToolContext(repo_root=tmp_path, enable_dangerous=True)

    events = await _collect(run_loop(
        provider=prov, model="m", system=None,
        messages=messages, tool_ctx=ctx, max_tokens=200,
    ))

    types = [e["event"] for e in events]
    assert "tool_call_start" in types
    assert "tool_call" in types
    assert "tool_result" in types
    assert types.count("assistant_message") == 2
    assert types[-1] == "done"

    # The conversation grew by: assistant(tool_use) + user(tool_result) + assistant(text) = 3.
    assert len(messages) == 4
    # The tool_result was wrapped as a user message per Anthropic protocol.
    assert messages[1]["role"] == "assistant"
    assert any(b.get("type") == "tool_use" for b in messages[1]["content"])
    assert messages[2]["role"] == "user"
    assert messages[2]["content"][0]["type"] == "tool_result"


async def test_loop_emits_error_on_provider_exception(tmp_path):
    class Boom:
        name = "boom"
        async def stream_turn(self, **kw):  # noqa: ARG002
            raise RuntimeError("provider down")
            yield  # pragma: no cover (make generator)

    messages = [{"role": "user", "content": [{"type": "text", "text": "?"}]}]
    events = await _collect(run_loop(
        provider=Boom(), model="m", system=None,
        messages=messages, tool_ctx=ToolContext(repo_root=tmp_path),
        max_tokens=100,
    ))
    assert events[-1]["event"] == "error"
    assert "provider down" in events[-1]["data"]["message"]


async def test_loop_hits_iteration_bound(tmp_path):
    """If the model keeps requesting tools forever, the loop bails safely."""
    forever_tool_use = [
        {"type": "tool_use_end", "id": "tu_x", "name": "project_status", "input": {}},
        {"type": "turn_end", "stop_reason": "tool_use",
         "usage": {"input_tokens": 1, "output_tokens": 1},
         "content": [{"type": "tool_use", "id": "tu_x",
                      "name": "project_status", "input": {}}]},
    ]
    prov = StubProvider(scripts=[forever_tool_use] * 3)
    (tmp_path / "artifacts" / "_registry").mkdir(parents=True)

    events = await _collect(run_loop(
        provider=prov, model="m", system=None,
        messages=[{"role": "user", "content": [{"type": "text", "text": "?"}]}],
        tool_ctx=ToolContext(repo_root=tmp_path, enable_dangerous=True),
        max_tokens=50, max_iterations=2,
    ))
    assert events[-1]["event"] == "error"
    assert "safety bound" in events[-1]["data"]["message"]
