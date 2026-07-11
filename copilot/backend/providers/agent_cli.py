"""AgentCliProvider — one spec-driven adapter for every local agent CLI.

Puffin ships bespoke providers for the two CLIs with rich native
integrations (Claude Code via the agent SDK, Codex via `codex exec --json`).
This module covers the rest of the coding-agent ecosystem — Gemini CLI,
Qwen Code, OpenCode, Cursor Agent, GitHub Copilot CLI — through a single
subprocess adapter, so supporting the next CLI is a catalog entry, not a
new provider class.

Each catalog entry (`AgentCliSpec`) declares how to invoke the binary in
headless mode, how the prompt is delivered (stdin vs argv), which flags to
add in safe vs dangerous mode, and how to parse the output:

  parse="text"   — stream raw stdout as text deltas (works with any CLI).
  parse="jsonl"  — tolerant JSONL event parser. Understands the
                   Claude-Code-style envelope Gemini emits with
                   `--output-format stream-json` (assistant / user /
                   result events), several flat event shapes, and falls
                   back to treating non-JSON lines as plain text — so a
                   CLI that ignores the flag still works.

Like the Codex provider, these CLIs run their own tools before returning;
the turn always ends with stop_reason="end_turn" so Puffin's registry does
not try to dispatch tool names it doesn't own.
"""
from __future__ import annotations

import asyncio
import codecs
import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator


# Windows caps a single argv string around 32K chars; leave headroom for the
# rest of the command line when the prompt is passed as an argument.
_ARG_PROMPT_MAX = 28_000

# Kill the CLI if it produces no output for this long (an interactive
# approval prompt we failed to suppress would otherwise hang the SSE
# stream forever).
_DEFAULT_IDLE_TIMEOUT_S = 300.0

# CSI + OSC escape sequences and bare carriage returns (spinner redraws).
_ANSI_RE = re.compile(
    r"\x1b\[[0-9;?]*[ -/]*[@-~]"          # CSI ... final byte
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC ... BEL / ST
    r"|\r(?!\n)"
)


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text).replace("\r\n", "\n")


@dataclass(frozen=True)
class AgentCliSpec:
    """How to drive one agent CLI in headless mode."""

    vendor: str
    """Vendor key used in `vendor:model` strings and the picker."""
    binary: str
    """Executable looked up on PATH (overridable per provider instance)."""
    label: str
    install_hint: str
    description: str
    parse: str = "text"
    """"text" (stream stdout) or "jsonl" (tolerant JSONL event parser)."""
    base_args: tuple[str, ...] = ()
    model_args: tuple[str, ...] = ()
    """Flags selecting the model; "{model}" is substituted. Skipped when
    the model is empty or "default" (the CLI's own config decides)."""
    safe_args: tuple[str, ...] = ()
    dangerous_args: tuple[str, ...] = ()
    prompt_style: str = "stdin"
    """"stdin" (piped, no length limit) or "arg" (appended to argv)."""
    prompt_args: tuple[str, ...] = ("{prompt}",)
    """argv tail for prompt_style="arg"; "{prompt}" is substituted."""

    def build_argv(
        self, *, cli_path: str, model: str, prompt: str, dangerous: bool,
    ) -> tuple[list[str], str | None]:
        """Return (argv, stdin_payload). stdin_payload is None for arg-style."""
        argv = [cli_path, *self.base_args]
        if model and model != "default":
            argv += [a.replace("{model}", model) for a in self.model_args]
        argv += list(self.dangerous_args if dangerous else self.safe_args)
        if self.prompt_style == "arg":
            clipped = prompt[-_ARG_PROMPT_MAX:]
            argv += [a.replace("{prompt}", clipped) for a in self.prompt_args]
            return argv, None
        return argv, prompt


AGENT_CLI_CATALOG: tuple[AgentCliSpec, ...] = (
    AgentCliSpec(
        vendor="gemini-cli",
        binary="gemini",
        label="Gemini CLI (local)",
        install_hint="npm i -g @google/gemini-cli",
        description=(
            "Google's Gemini CLI in headless mode with JSONL streaming. Uses "
            "your local `gemini` auth (OAuth or GEMINI_API_KEY). The CLI's "
            "own tools run sandboxed by its approval mode; Puffin tools are "
            "not auto-mounted."
        ),
        parse="jsonl",
        base_args=("--output-format", "stream-json"),
        model_args=("-m", "{model}"),
        safe_args=("--approval-mode", "default"),
        dangerous_args=("--approval-mode", "yolo"),
        prompt_style="stdin",
    ),
    AgentCliSpec(
        vendor="qwen-code",
        binary="qwen",
        label="Qwen Code (local)",
        install_hint="npm i -g @qwen-code/qwen-code",
        description=(
            "Qwen Code CLI (Gemini CLI fork) in headless mode. Uses your "
            "local `qwen` auth and model config."
        ),
        parse="text",
        model_args=("-m", "{model}"),
        dangerous_args=("--yolo",),
        prompt_style="stdin",
    ),
    AgentCliSpec(
        vendor="opencode",
        binary="opencode",
        label="OpenCode (local)",
        install_hint="npm i -g opencode-ai",
        description=(
            "OpenCode `run` in non-interactive mode. Model strings use "
            "OpenCode's provider/model form, e.g. "
            "`opencode:anthropic/claude-sonnet-4-6`."
        ),
        parse="text",
        base_args=("run",),
        model_args=("--model", "{model}"),
        prompt_style="arg",
        prompt_args=("{prompt}",),
    ),
    AgentCliSpec(
        vendor="cursor-agent",
        binary="cursor-agent",
        label="Cursor Agent (local)",
        install_hint="curl https://cursor.com/install -fsS | bash",
        description=(
            "Cursor's agent CLI in print mode. Uses your `cursor-agent` "
            "login; --force (file edits) only with dangerous tools enabled."
        ),
        parse="text",
        base_args=("--output-format", "text"),
        model_args=("--model", "{model}"),
        dangerous_args=("--force",),
        prompt_style="arg",
        prompt_args=("-p", "{prompt}"),
    ),
    AgentCliSpec(
        vendor="copilot-cli",
        binary="copilot",
        label="GitHub Copilot CLI (local)",
        install_hint="npm i -g @github/copilot",
        description=(
            "GitHub Copilot coding agent CLI in prompt mode. Uses your "
            "GitHub auth; tool execution is only approved automatically "
            "when dangerous tools are enabled."
        ),
        parse="text",
        model_args=("--model", "{model}"),
        dangerous_args=("--allow-all-tools",),
        prompt_style="arg",
        prompt_args=("-p", "{prompt}"),
    ),
)


AGENT_CLI_SPECS: dict[str, AgentCliSpec] = {s.vendor: s for s in AGENT_CLI_CATALOG}


async def probe_cli_version(cli_path: str, timeout_s: float = 8.0) -> str | None:
    """Best-effort `<cli> --version` → the version line, or None."""
    try:
        proc = await asyncio.create_subprocess_exec(
            cli_path, "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except (OSError, asyncio.TimeoutError):
        return None
    lines = [
        _strip_ansi(line).strip()
        for line in out.decode("utf-8", errors="replace").splitlines()
        if line.strip()
    ]
    # Shell autorun scripts (doskey banners etc.) can print before the CLI
    # does — prefer the first line that actually looks like a version.
    for line in lines:
        if re.search(r"\d+\.\d+", line):
            return line
    return lines[0] if lines else None


class AgentCliProvider:
    """Spec-driven subprocess provider for local agent CLIs."""

    def __init__(
        self,
        spec: AgentCliSpec,
        *,
        repo_root: str | None = None,
        cli_path: str | None = None,
        enable_dangerous: bool = False,
        idle_timeout_s: float = _DEFAULT_IDLE_TIMEOUT_S,
    ) -> None:
        self.spec = spec
        self.name = f"agent_cli:{spec.vendor}"
        self.repo_root = Path(repo_root) if repo_root else Path.cwd()
        self.cli_path = cli_path or shutil.which(spec.binary) or spec.binary
        self.enable_dangerous = enable_dangerous
        self.idle_timeout_s = idle_timeout_s

    @staticmethod
    def is_available(spec: AgentCliSpec, cli_path: str | None = None) -> bool:
        return bool(shutil.which(cli_path or spec.binary))

    async def stream_turn(
        self,
        *,
        model: str,
        system: str | None,             # noqa: ARG002 — the CLI has its own
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],    # noqa: ARG002 — the CLI uses its own
        max_tokens: int,                # noqa: ARG002 — controlled by the CLI
        tool_ctx: Any = None,
    ) -> AsyncIterator[dict[str, Any]]:
        # Scope the CLI to the chat thread's project, not the startup default.
        run_root = Path(tool_ctx.repo_root) if tool_ctx else self.repo_root
        prompt = _messages_to_prompt(messages)
        if not prompt.strip():
            yield _end_turn([], 0, 0)
            return

        argv, stdin_payload = self.spec.build_argv(
            cli_path=self.cli_path, model=model, prompt=prompt,
            dangerous=self.enable_dangerous,
        )
        env = {
            **os.environ,
            # Keep decorative output out of the stream we parse.
            "NO_COLOR": "1",
            "FORCE_COLOR": "0",
            "TERM": "dumb",
        }
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(run_root),
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                # Same headroom as the Codex provider — agent CLIs emit
                # single JSONL lines far beyond asyncio's 64KB default.
                limit=16 * 1024 * 1024,
            )
        except FileNotFoundError:
            msg = (
                f"{self.spec.binary} CLI not found at {self.cli_path!r}. "
                f"Install: `{self.spec.install_hint}`."
            )
            yield {"type": "text_delta", "text": msg}
            yield _end_turn([{"type": "text", "text": msg}], 0, 0)
            return

        assert proc.stdin is not None
        if stdin_payload is not None:
            proc.stdin.write(stdin_payload.encode("utf-8"))
            await proc.stdin.drain()
        proc.stdin.close()

        state = _TurnState()
        try:
            if self.spec.parse == "jsonl":
                stream = self._stream_jsonl(proc, state)
            else:
                stream = self._stream_text(proc, state)
            async for evt in stream:
                yield evt
        except asyncio.TimeoutError:
            proc.kill()
            text = (
                f"\n_{self.spec.binary} produced no output for "
                f"{int(self.idle_timeout_s)}s and was terminated. It may have "
                "been waiting for interactive input._"
            )
            state.record_text(text)
            yield {"type": "text_delta", "text": text}
            yield _end_turn(state.content, state.usage_in, state.usage_out)
            return

        await proc.wait()
        if proc.returncode and proc.returncode != 0:
            assert proc.stderr is not None
            err_blob = (await proc.stderr.read()).decode("utf-8", errors="replace")
            err_blob = _strip_ansi(err_blob)[-400:].strip()
            if err_blob:
                text = f"\n_{self.spec.binary} exited {proc.returncode}: {err_blob}_"
                state.record_text(text)
                yield {"type": "text_delta", "text": text}

        # Tool calls the CLI reported but never resolved — flip their cards
        # to "done" so the frontend isn't stuck on "calling…".
        for tid, block in state.tools.items():
            if tid in state.tool_results:
                continue
            yield {
                "type": "tool_use_result",
                "id": tid,
                "name": block.get("name", "tool"),
                "result": {
                    "kind": "agent_cli_tool_result",
                    "status": "unknown",
                    "output": (
                        f"{self.spec.binary} ended before reporting this "
                        "tool result."
                    ),
                },
            }

        yield _end_turn(state.content, state.usage_in, state.usage_out)

    # ----- text mode ------------------------------------------------------
    async def _stream_text(
        self, proc: asyncio.subprocess.Process, state: _TurnState,
    ) -> AsyncIterator[dict[str, Any]]:
        assert proc.stdout is not None
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        while True:
            chunk = await asyncio.wait_for(
                proc.stdout.read(65536), timeout=self.idle_timeout_s)
            if not chunk:
                break
            text = _strip_ansi(decoder.decode(chunk))
            if text:
                state.record_text(text)
                yield {"type": "text_delta", "text": text}
        tail = _strip_ansi(decoder.decode(b"", final=True))
        if tail:
            state.record_text(tail)
            yield {"type": "text_delta", "text": tail}

    # ----- jsonl mode -----------------------------------------------------
    async def _stream_jsonl(
        self, proc: asyncio.subprocess.Process, state: _TurnState,
    ) -> AsyncIterator[dict[str, Any]]:
        assert proc.stdout is not None
        # Non-JSON lines BEFORE the first event are shell/launcher preamble
        # (cmd AutoRun banners, "Loaded cached credentials.", …) — buffer
        # them, and drop them once structured events arrive. If no JSON ever
        # shows up (CLI ignored --output-format), flush the buffer as text.
        preamble: list[str] = []
        saw_json = False
        while True:
            line = await asyncio.wait_for(
                proc.stdout.readline(), timeout=self.idle_timeout_s)
            if not line:
                break
            raw = line.decode("utf-8", errors="replace")
            try:
                evt = json.loads(raw)
                if not isinstance(evt, dict):
                    raise ValueError
            except (json.JSONDecodeError, ValueError):
                text = _strip_ansi(raw)
                if not text.strip():
                    continue
                if not saw_json:
                    preamble.append(text)
                    continue
                state.record_text(text)
                yield {"type": "text_delta", "text": text}
                continue
            saw_json = True
            preamble.clear()
            for out in self._map_jsonl_event(evt, state):
                yield out
        if not saw_json and preamble:
            text = "".join(preamble)
            state.record_text(text)
            yield {"type": "text_delta", "text": text}

    def _map_jsonl_event(
        self, evt: dict[str, Any], state: _TurnState,
    ) -> list[dict[str, Any]]:
        """Translate one JSONL event into StreamEvents. Tolerates the
        Claude-Code-style envelope (Gemini stream-json) and flat shapes."""
        out: list[dict[str, Any]] = []
        etype = evt.get("type")

        # Claude-Code-style: {"type":"assistant","message":{"content":[...]}}
        if etype == "assistant" and isinstance(evt.get("message"), dict):
            for block in evt["message"].get("content", []) or []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text" and block.get("text"):
                    state.record_text(str(block["text"]))
                    out.append({"type": "text_delta", "text": str(block["text"])})
                elif block.get("type") == "tool_use":
                    out += state.start_tool(
                        block.get("id"), block.get("name"),
                        block.get("input") or {},
                    )
            return out

        # Claude-Code-style tool results ride on user messages.
        if etype == "user" and isinstance(evt.get("message"), dict):
            for block in evt["message"].get("content", []) or []:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    out += state.finish_tool(
                        block.get("tool_use_id"),
                        content=block.get("content"),
                        is_error=bool(block.get("is_error")),
                    )
            return out

        # Final result event: {"type":"result","result":...,"usage":{...}}
        # or Gemini's single-JSON shape {"response":...,"stats":{...}}.
        if etype == "result" or "response" in evt:
            text = str(evt.get("result") or evt.get("response") or "")
            if text and text != state.text:
                state.record_text(text)
                out.append({"type": "text_delta", "text": text})
            usage_in, usage_out = _extract_usage(evt)
            state.usage_in = max(state.usage_in, usage_in)
            state.usage_out = max(state.usage_out, usage_out)
            return out

        # Flat text-ish events.
        if etype in ("text", "content", "message_delta", "agent_message_delta"):
            text = str(evt.get("text") or evt.get("delta") or evt.get("content") or "")
            if text:
                state.record_text(text)
                out.append({"type": "text_delta", "text": text})
            return out

        # Flat tool events.
        if etype in ("tool_call", "tool_use"):
            tid = evt.get("id") or evt.get("call_id")
            name = evt.get("name") or evt.get("tool_name") or "tool"
            inp = evt.get("input") or evt.get("args") or evt.get("arguments") or {}
            return state.start_tool(tid, name, inp if isinstance(inp, dict) else {})
        if etype == "tool_result":
            return state.finish_tool(
                evt.get("id") or evt.get("tool_use_id") or evt.get("call_id"),
                content=evt.get("output") or evt.get("content"),
                is_error=bool(evt.get("is_error") or evt.get("error")),
            )

        if etype == "error":
            msg = str(evt.get("message") or evt.get("error") or "")
            if msg:
                text = f"\n_{self.spec.binary} error: {msg}_"
                state.record_text(text)
                out.append({"type": "text_delta", "text": text})
        return out


class _TurnState:
    """Accumulates the content list + usage across one CLI run."""

    def __init__(self) -> None:
        self.content: list[dict[str, Any]] = []
        self.text = ""
        self.tools: dict[str, dict[str, Any]] = {}
        self.tool_results: set[str] = set()
        self.usage_in = 0
        self.usage_out = 0

    def record_text(self, text: str) -> None:
        if not text:
            return
        self.text += text
        if self.content and self.content[-1].get("type") == "text":
            self.content[-1]["text"] = str(self.content[-1]["text"]) + text
        else:
            self.content.append({"type": "text", "text": text})

    def start_tool(
        self, tid: Any, name: Any, inp: dict[str, Any],
    ) -> list[dict[str, Any]]:
        tid = str(tid or f"agent_cli_{len(self.tools)}")
        name = str(name or "tool")
        if tid in self.tools:
            if inp:
                self.tools[tid]["input"] = inp
            return []
        block = {"type": "tool_use", "id": tid, "name": name, "input": inp}
        self.tools[tid] = block
        self.content.append(block)
        return [
            {"type": "tool_use_start", "id": tid, "name": name},
            {"type": "tool_use_end", "id": tid, "name": name, "input": inp},
        ]

    def finish_tool(
        self, tid: Any, *, content: Any, is_error: bool,
    ) -> list[dict[str, Any]]:
        tid = str(tid or "")
        if not tid or tid in self.tool_results:
            return []
        self.tool_results.add(tid)
        block = self.tools.get(tid, {})
        return [{
            "type": "tool_use_result",
            "id": tid,
            "name": block.get("name", "tool"),
            "result": {
                "kind": "agent_cli_tool_result",
                "status": "error" if is_error else "completed",
                "ok": not is_error,
                "output": _stringify(content),
            },
        }]


def _stringify(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        # Anthropic-style block list.
        return "".join(
            str(b.get("text", "")) if isinstance(b, dict) else str(b)
            for b in content
        )
    return json.dumps(content, default=str)


def _extract_usage(evt: dict[str, Any]) -> tuple[int, int]:
    usage = evt.get("usage")
    if isinstance(usage, dict):
        return (
            int(usage.get("input_tokens", 0) or 0),
            int(usage.get("output_tokens", 0) or 0),
        )
    # Gemini CLI stats: {"models": {"<model>": {"tokens": {"prompt": n,
    # "candidates": n, ...}}}}
    stats = evt.get("stats")
    if isinstance(stats, dict) and isinstance(stats.get("models"), dict):
        usage_in = usage_out = 0
        for m in stats["models"].values():
            tokens = m.get("tokens", {}) if isinstance(m, dict) else {}
            usage_in += int(tokens.get("prompt", 0) or 0)
            usage_out += int(tokens.get("candidates", 0) or 0)
        return usage_in, usage_out
    return 0, 0


def _end_turn(
    content: list[dict[str, Any]], usage_in: int, usage_out: int,
) -> dict[str, Any]:
    return {
        "type": "turn_end",
        # The CLI runs its own tools before returning; end_turn keeps
        # Puffin's registry from dispatching tool names it doesn't own.
        "stop_reason": "end_turn",
        "usage": {"input_tokens": usage_in, "output_tokens": usage_out},
        "content": content or [{"type": "text", "text": ""}],
    }


def _messages_to_prompt(messages: list[dict[str, Any]]) -> str:
    """Same trick as the Claude Code / Codex providers — flatten history."""
    if not messages:
        return ""
    *history, last = messages
    parts: list[str] = []
    for m in history:
        role = m.get("role")
        for b in m.get("content", []) or []:
            if b.get("type") == "text":
                parts.append(f"[{role}] {b.get('text', '')}")
    new_msg = ""
    for b in last.get("content", []) or []:
        if b.get("type") == "text":
            new_msg += b.get("text", "")
    if parts:
        return (
            "<conversation_history>\n" + "\n".join(parts)
            + "\n</conversation_history>\n\n" + new_msg
        )
    return new_msg
