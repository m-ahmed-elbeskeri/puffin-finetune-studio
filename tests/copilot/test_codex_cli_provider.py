from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from copilot.backend.providers.codex_cli import CodexCliProvider

pytestmark = pytest.mark.asyncio


class _FakeStdin:
    def __init__(self) -> None:
        self.data = b""
        self.closed = False

    def write(self, data: bytes) -> None:
        self.data += data

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class _FakeStdout:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self.lines = [(json.dumps(evt) + "\n").encode("utf-8") for evt in events]

    async def readline(self) -> bytes:
        if not self.lines:
            return b""
        return self.lines.pop(0)


class _FakeStderr:
    async def read(self) -> bytes:
        return b""


class _FakeProc:
    def __init__(self, events: list[dict[str, Any]], returncode: int = 0) -> None:
        self.stdin = _FakeStdin()
        self.stdout = _FakeStdout(events)
        self.stderr = _FakeStderr()
        self.returncode = returncode

    async def wait(self) -> int:
        return self.returncode


async def _collect(provider: CodexCliProvider) -> list[dict[str, Any]]:
    return [
        evt
        async for evt in provider.stream_turn(
            model="default",
            system=None,
            messages=[
                {
                    "role": "user",
                    "content": [{"type": "text", "text": "what directory?"}],
                }
            ],
            tools=[],
            max_tokens=100,
        )
    ]


async def test_codex_cli_streams_command_execution_as_provider_resolved_tool(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    events = [
        {"type": "thread.started", "thread_id": "t"},
        {"type": "turn.started"},
        {
            "type": "item.started",
            "item": {
                "id": "item_1",
                "type": "command_execution",
                "command": "powershell -Command Get-Location",
                "aggregated_output": "",
                "exit_code": None,
                "status": "in_progress",
            },
        },
        {
            "type": "item.completed",
            "item": {
                "id": "item_1",
                "type": "command_execution",
                "command": "powershell -Command Get-Location",
                "aggregated_output": "C:\\Users\\A\\Documents\\puffin-finetune-studio",
                "exit_code": 0,
                "status": "completed",
            },
        },
        {
            "type": "item.completed",
            "item": {
                "id": "item_2",
                "type": "agent_message",
                "text": "puffin-finetune-studio",
            },
        },
        {
            "type": "turn.completed",
            "usage": {"input_tokens": 10, "output_tokens": 4},
        },
    ]
    proc = _FakeProc(events)

    async def fake_exec(*args, **kwargs):
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    out = await _collect(CodexCliProvider(repo_root=str(tmp_path), cli_path="codex"))

    assert proc.stdin.closed is True
    assert b"what directory?" in proc.stdin.data

    assert out[0] == {
        "type": "tool_use_start",
        "id": "item_1",
        "name": "codex_command",
    }
    assert out[1] == {
        "type": "tool_use_end",
        "id": "item_1",
        "name": "codex_command",
        "input": {"command": "powershell -Command Get-Location"},
    }
    assert out[2]["type"] == "tool_use_result"
    assert out[2]["id"] == "item_1"
    assert out[2]["result"] == {
        "kind": "codex_command_result",
        "command": "powershell -Command Get-Location",
        "status": "completed",
        "exit_code": 0,
        "ok": True,
        "output": "C:\\Users\\A\\Documents\\puffin-finetune-studio",
    }
    assert {"type": "text_delta", "text": "puffin-finetune-studio"} in out

    final = out[-1]
    assert final["type"] == "turn_end"
    assert final["stop_reason"] == "end_turn"
    assert final["usage"] == {"input_tokens": 10, "output_tokens": 4}
    assert final["content"] == [
        {
            "type": "tool_use",
            "id": "item_1",
            "name": "codex_command",
            "input": {"command": "powershell -Command Get-Location"},
        },
        {"type": "text", "text": "puffin-finetune-studio"},
    ]


async def test_codex_cli_ignores_local_agent_role_warnings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    events = [
        {
            "type": "item.completed",
            "item": {
                "id": "item_0",
                "type": "error",
                "message": "Ignoring malformed agent role definition: local file",
            },
        },
        {
            "type": "item.completed",
            "item": {"id": "item_1", "type": "agent_message", "text": "ok"},
        },
        {
            "type": "turn.completed",
            "usage": {"input_tokens": 1, "output_tokens": 1},
        },
    ]

    async def fake_exec(*args, **kwargs):
        return _FakeProc(events)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    out = await _collect(CodexCliProvider(repo_root=str(tmp_path), cli_path="codex"))

    text_events = [evt for evt in out if evt["type"] == "text_delta"]
    assert text_events == [{"type": "text_delta", "text": "ok"}]
    assert out[-1]["content"] == [{"type": "text", "text": "ok"}]
