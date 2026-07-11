from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from copilot.backend.providers.agent_cli import (
    AGENT_CLI_CATALOG,
    AGENT_CLI_SPECS,
    AgentCliProvider,
    AgentCliSpec,
)
from copilot.backend.providers.factory import AVAILABLE_MODELS

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
    """Serves fixed byte chunks to both read(n) and readline()."""

    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = list(chunks)

    async def read(self, n: int = -1) -> bytes:
        if not self.chunks:
            return b""
        return self.chunks.pop(0)

    async def readline(self) -> bytes:
        if not self.chunks:
            return b""
        return self.chunks.pop(0)


class _FakeStderr:
    def __init__(self, blob: bytes = b"") -> None:
        self.blob = blob

    async def read(self) -> bytes:
        return self.blob


class _FakeProc:
    def __init__(
        self,
        chunks: list[bytes],
        returncode: int = 0,
        stderr: bytes = b"",
    ) -> None:
        self.stdin = _FakeStdin()
        self.stdout = _FakeStdout(chunks)
        self.stderr = _FakeStderr(stderr)
        self.returncode = returncode
        self.killed = False

    async def wait(self) -> int:
        return self.returncode

    def kill(self) -> None:
        self.killed = True


def _jsonl(events: list[dict[str, Any]]) -> list[bytes]:
    return [(json.dumps(e) + "\n").encode("utf-8") for e in events]


async def _collect(
    provider: AgentCliProvider,
    prompt: str = "what directory?",
) -> list[dict[str, Any]]:
    return [
        evt
        async for evt in provider.stream_turn(
            model="default",
            system=None,
            messages=[
                {
                    "role": "user",
                    "content": [{"type": "text", "text": prompt}],
                }
            ],
            tools=[],
            max_tokens=100,
        )
    ]


def _patch_exec(monkeypatch: pytest.MonkeyPatch, proc: _FakeProc) -> list[Any]:
    calls: list[Any] = []

    async def fake_exec(*args, **kwargs):
        calls.append((args, kwargs))
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    return calls


# ---------------------------------------------------------------------------
# Text mode
# ---------------------------------------------------------------------------
async def test_text_mode_streams_stdout_and_strips_ansi(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    spec = AGENT_CLI_SPECS["opencode"]
    proc = _FakeProc([b"\x1b[32mhello ", b"world\x1b[0m\n"])
    calls = _patch_exec(monkeypatch, proc)

    out = await _collect(AgentCliProvider(spec, repo_root=str(tmp_path), cli_path="opencode"))

    argv = calls[0][0]
    assert argv[0] == "opencode"
    assert argv[1] == "run"
    # Arg-style prompt: delivered on argv, nothing written to stdin.
    assert "what directory?" in argv[-1]
    assert proc.stdin.data == b""
    assert proc.stdin.closed is True

    deltas = [e["text"] for e in out if e["type"] == "text_delta"]
    assert deltas == ["hello ", "world\n"]

    final = out[-1]
    assert final["type"] == "turn_end"
    assert final["stop_reason"] == "end_turn"
    assert final["content"] == [{"type": "text", "text": "hello world\n"}]


async def test_text_mode_surfaces_nonzero_exit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    spec = AGENT_CLI_SPECS["copilot-cli"]
    proc = _FakeProc([], returncode=2, stderr=b"not logged in")
    _patch_exec(monkeypatch, proc)

    out = await _collect(AgentCliProvider(spec, repo_root=str(tmp_path), cli_path="copilot"))

    deltas = "".join(e["text"] for e in out if e["type"] == "text_delta")
    assert "exited 2" in deltas
    assert "not logged in" in deltas


# ---------------------------------------------------------------------------
# JSONL mode (Gemini-style stream-json)
# ---------------------------------------------------------------------------
async def test_jsonl_mode_parses_claude_style_envelope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    spec = AGENT_CLI_SPECS["gemini-cli"]
    events = [
        {"type": "system", "subtype": "init"},
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "checking"},
                    {
                        "type": "tool_use",
                        "id": "tu_1",
                        "name": "run_shell_command",
                        "input": {"command": "pwd"},
                    },
                ]
            },
        },
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tu_1",
                        "content": "C:/repo",
                        "is_error": False,
                    }
                ]
            },
        },
        {
            "type": "result",
            "result": "checking → it's C:/repo",
            "usage": {"input_tokens": 12, "output_tokens": 5},
        },
    ]
    proc = _FakeProc(_jsonl(events))
    calls = _patch_exec(monkeypatch, proc)

    out = await _collect(AgentCliProvider(spec, repo_root=str(tmp_path), cli_path="gemini"))

    argv = calls[0][0]
    assert "--output-format" in argv and "stream-json" in argv
    # stdin-style prompt.
    assert b"what directory?" in proc.stdin.data
    assert proc.stdin.closed is True

    assert {"type": "text_delta", "text": "checking"} in out
    assert {
        "type": "tool_use_end",
        "id": "tu_1",
        "name": "run_shell_command",
        "input": {"command": "pwd"},
    } in out
    results = [e for e in out if e["type"] == "tool_use_result"]
    assert len(results) == 1
    assert results[0]["id"] == "tu_1"
    assert results[0]["result"]["ok"] is True
    assert results[0]["result"]["output"] == "C:/repo"

    final = out[-1]
    assert final["type"] == "turn_end"
    assert final["usage"] == {"input_tokens": 12, "output_tokens": 5}
    assert final["content"][0] == {"type": "text", "text": "checking"}
    assert final["content"][1]["type"] == "tool_use"


async def test_jsonl_mode_falls_back_to_text_for_non_json_lines(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    spec = AGENT_CLI_SPECS["gemini-cli"]
    proc = _FakeProc([b"plain answer, no JSON here\n"])
    _patch_exec(monkeypatch, proc)

    out = await _collect(AgentCliProvider(spec, repo_root=str(tmp_path), cli_path="gemini"))

    deltas = [e["text"] for e in out if e["type"] == "text_delta"]
    assert deltas == ["plain answer, no JSON here\n"]


async def test_jsonl_mode_drops_launcher_preamble_before_first_event(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    spec = AGENT_CLI_SPECS["gemini-cli"]
    chunks = [
        b"File not found - C:\\autorun\\doskey-macros.txt\n",
        b"Loaded cached credentials.\n",
        *_jsonl(
            [
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {"type": "text", "text": "hi"},
                        ]
                    },
                },
            ]
        ),
    ]
    proc = _FakeProc(chunks)
    _patch_exec(monkeypatch, proc)

    out = await _collect(AgentCliProvider(spec, repo_root=str(tmp_path), cli_path="gemini"))

    deltas = [e["text"] for e in out if e["type"] == "text_delta"]
    assert deltas == ["hi"]
    assert out[-1]["content"] == [{"type": "text", "text": "hi"}]


async def test_jsonl_mode_extracts_gemini_stats_and_dedupes_result_text(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    spec = AGENT_CLI_SPECS["gemini-cli"]
    events = [
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "42"},
                ]
            },
        },
        {
            "response": "42",
            "stats": {
                "models": {
                    "gemini-2.5-pro": {
                        "tokens": {"prompt": 100, "candidates": 7, "total": 107},
                    }
                }
            },
        },
    ]
    proc = _FakeProc(_jsonl(events))
    _patch_exec(monkeypatch, proc)

    out = await _collect(AgentCliProvider(spec, repo_root=str(tmp_path), cli_path="gemini"))

    # The final result text equals what was already streamed — no re-emit.
    deltas = [e["text"] for e in out if e["type"] == "text_delta"]
    assert deltas == ["42"]
    assert out[-1]["usage"] == {"input_tokens": 100, "output_tokens": 7}


async def test_jsonl_mode_synthesises_result_for_unresolved_tools(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    spec = AGENT_CLI_SPECS["gemini-cli"]
    events = [
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tu_9",
                        "name": "write_file",
                        "input": {"path": "x"},
                    },
                ]
            },
        },
    ]
    proc = _FakeProc(_jsonl(events))
    _patch_exec(monkeypatch, proc)

    out = await _collect(AgentCliProvider(spec, repo_root=str(tmp_path), cli_path="gemini"))

    results = [e for e in out if e["type"] == "tool_use_result"]
    assert len(results) == 1
    assert results[0]["id"] == "tu_9"
    assert results[0]["result"]["status"] == "unknown"


# ---------------------------------------------------------------------------
# Spec / argv construction
# ---------------------------------------------------------------------------
async def test_build_argv_model_and_danger_flags() -> None:
    spec = AGENT_CLI_SPECS["gemini-cli"]
    argv, payload = spec.build_argv(
        cli_path="gemini", model="gemini-2.5-pro", prompt="hi", dangerous=True
    )
    assert argv == [
        "gemini",
        "--output-format",
        "stream-json",
        "-m",
        "gemini-2.5-pro",
        "--approval-mode",
        "yolo",
    ]
    assert payload == "hi"

    argv, payload = spec.build_argv(
        cli_path="gemini", model="default", prompt="hi", dangerous=False
    )
    assert "-m" not in argv
    assert argv[-2:] == ["--approval-mode", "default"]


async def test_build_argv_clips_arg_style_prompt() -> None:
    spec = AGENT_CLI_SPECS["cursor-agent"]
    long_prompt = "x" * 100_000
    argv, payload = spec.build_argv(
        cli_path="cursor-agent", model="default", prompt=long_prompt, dangerous=False
    )
    assert payload is None
    assert len(argv[-1]) < 32_000
    # Keep the tail — that's where the newest user message lives.
    assert argv[-1] == long_prompt[-len(argv[-1]) :]


async def test_catalog_vendors_are_unique_and_in_available_models() -> None:
    vendors = [spec.vendor for spec in AGENT_CLI_CATALOG]
    assert len(vendors) == len(set(vendors))
    picker_vendors = {m["vendor"] for m in AVAILABLE_MODELS}
    for spec in AGENT_CLI_CATALOG:
        assert spec.vendor in picker_vendors
        assert spec.parse in ("text", "jsonl")
        assert spec.prompt_style in ("stdin", "arg")
        if spec.prompt_style == "arg":
            assert any("{prompt}" in a for a in spec.prompt_args)


async def test_missing_binary_yields_install_hint(tmp_path) -> None:
    spec = AgentCliSpec(
        vendor="ghost",
        binary="definitely-not-installed-xyz",
        label="Ghost",
        install_hint="npm i -g ghost",
        description="",
        parse="text",
    )
    provider = AgentCliProvider(
        spec, repo_root=str(tmp_path), cli_path="definitely-not-installed-xyz-binary"
    )
    out = await _collect(provider)
    text = "".join(e.get("text", "") for e in out if e["type"] == "text_delta")
    assert "not found" in text
    assert "npm i -g ghost" in text
    assert out[-1]["type"] == "turn_end"
