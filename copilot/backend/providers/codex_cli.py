"""CodexCliProvider — spawns the local `codex exec --json` CLI.

This is the genuine Codex equivalent of the Claude Code provider: it shells
out to the user's installed `codex` binary, streams JSONL events, and
translates them into our StreamEvent envelope. Auth + model selection are
inherited from the user's `~/.codex/config.toml`.

For OpenAI's chat-completions API (with `gpt-5` / `gpt-5-codex`), see the
OpenAICodexProvider in openai_codex.py. Both can coexist; the factory wires
the one for which credentials/CLIs are present.

Note: this provider does NOT pipe our Puffin tools into Codex (Codex doesn't
yet have an SDK MCP analogue we can register in-process). Codex DOES have
its own Bash/Read/Edit; users can also register Puffin as an external MCP
server via `codex mcp add puffin -- python -m copilot.backend.mcp_server`
(not implemented here).
"""
from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from typing import Any, AsyncIterator


class CodexCliProvider:
    name = "codex_cli"

    def __init__(
        self,
        *,
        repo_root: str | None = None,
        cli_path: str | None = None,
        enable_dangerous: bool = False,
    ) -> None:
        self.repo_root = Path(repo_root) if repo_root else Path.cwd()
        self.cli_path = cli_path or shutil.which("codex") or "codex"
        self.enable_dangerous = enable_dangerous

    @staticmethod
    def is_available(cli_path: str | None = None) -> bool:
        return bool(shutil.which(cli_path or "codex"))

    async def stream_turn(
        self,
        *,
        model: str,
        system: str | None,             # noqa: ARG002 — codex CLI has its own
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],    # noqa: ARG002 — codex uses its own
        max_tokens: int,                # noqa: ARG002 — controlled by the CLI
        tool_ctx: Any = None,
    ) -> AsyncIterator[dict[str, Any]]:
        # Scope the CLI to the chat thread's project, not the startup default.
        run_root = Path(tool_ctx.repo_root) if tool_ctx else self.repo_root
        prompt = _messages_to_prompt(messages)
        if not prompt.strip():
            yield {
                "type": "turn_end", "stop_reason": "end_turn",
                "usage": {"input_tokens": 0, "output_tokens": 0},
                "content": [{"type": "text", "text": ""}],
            }
            return

        args = [
            self.cli_path, "exec",
            "--json",
            "--ephemeral",
            "--skip-git-repo-check",
            "-C", str(run_root),
        ]
        if model and model not in ("default", "codex"):
            args += ["-m", model]
        if self.enable_dangerous:
            args.append("--dangerously-bypass-approvals-and-sandbox")
        else:
            args += ["--sandbox", "read-only"]
        # Prompt is read from stdin so we don't hit shell-arg length limits.
        args.append("-")

        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                cwd=str(run_root),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                # Codex JSONL events (large tool output, diffs, full agent
                # messages) routinely blow past asyncio's default 64KB readline
                # limit, which surfaces as `ValueError: Separator is not found,
                # and chunk exceed the limit`. Give the stdout reader plenty of
                # headroom.
                limit=16 * 1024 * 1024,
            )
        except FileNotFoundError:
            msg = f"codex CLI not found at {self.cli_path!r}. Install: `npm i -g @openai/codex`."
            yield {"type": "text_delta", "text": msg}
            yield {
                "type": "turn_end", "stop_reason": "end_turn",
                "usage": {"input_tokens": 0, "output_tokens": 0},
                "content": [{"type": "text", "text": msg}],
            }
            return

        assert proc.stdin is not None
        proc.stdin.write(prompt.encode("utf-8"))
        await proc.stdin.drain()
        proc.stdin.close()

        text_parts: list[str] = []
        content: list[dict[str, Any]] = []
        command_tools: dict[str, dict[str, Any]] = {}
        command_results: set[str] = set()
        usage_in = 0
        usage_out = 0

        def record_text(text: str) -> None:
            if not text:
                return
            text_parts.append(text)
            if content and content[-1].get("type") == "text":
                content[-1]["text"] = str(content[-1].get("text", "")) + text
            else:
                content.append({"type": "text", "text": text})

        assert proc.stdout is not None
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            try:
                evt = json.loads(line.decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                continue

            # Codex JSONL is still stabilising; tolerate both the current
            # `item.started/completed` envelope and older flat event names.
            etype = evt.get("type") or evt.get("msg", {}).get("type")
            payload = evt.get("msg") if isinstance(evt.get("msg"), dict) else evt
            item = payload.get("item") if isinstance(payload.get("item"), dict) else None
            item_type = item.get("type") if item else None

            if etype in ("item.started", "item.updated", "item.completed") and item_type == "command_execution":
                assert item is not None
                tid, name, inp = _command_tool(item, len(command_tools))
                existing = command_tools.get(tid)
                if existing is None:
                    block = {
                        "type": "tool_use", "id": tid,
                        "name": name, "input": inp,
                    }
                    command_tools[tid] = block
                    content.append(block)
                    yield {"type": "tool_use_start", "id": tid, "name": name}
                    yield {
                        "type": "tool_use_end",
                        "id": tid, "name": name, "input": inp,
                    }
                elif inp.get("command"):
                    existing["input"] = inp

                if etype == "item.completed" and tid not in command_results:
                    result = _command_result(item)
                    command_results.add(tid)
                    yield {
                        "type": "tool_use_result",
                        "id": tid,
                        "name": name,
                        "result": result,
                    }
                continue

            if etype == "item.completed" and item_type == "agent_message":
                assert item is not None
                text = item.get("text") or item.get("content") or ""
                if text and "".join(text_parts) != text:
                    record_text(text)
                    yield {"type": "text_delta", "text": text}
            elif etype == "item.completed" and item_type == "error":
                assert item is not None
                err = str(item.get("message") or "")
                if err and not _ignore_codex_error(err):
                    text = f"\n_Codex error: {err}_"
                    record_text(text)
                    yield {"type": "text_delta", "text": text}
            elif etype == "turn.completed":
                usage = payload.get("usage", {}) or {}
                usage_in = int(usage.get("input_tokens", 0) or 0)
                usage_out = int(usage.get("output_tokens", 0) or 0)
            elif etype in ("agent_message_delta", "message_delta", "text"):
                text = (
                    payload.get("delta")
                    or payload.get("text")
                    or payload.get("content")
                    or ""
                )
                if text:
                    record_text(text)
                    yield {"type": "text_delta", "text": text}
            elif etype in ("agent_message", "assistant_message"):
                text = payload.get("text") or payload.get("content") or ""
                if text and "".join(text_parts) != text:
                    # Full message in one go (no deltas were sent).
                    record_text(text)
                    yield {"type": "text_delta", "text": text}
            elif etype in ("tool_call", "exec_command_begin", "tool_use"):
                name = (
                    payload.get("name")
                    or payload.get("tool_name")
                    or ("codex_command" if payload.get("command") else "tool")
                )
                tid = (
                    payload.get("id")
                    or payload.get("call_id")
                    or f"codex_{len(command_tools)}"
                )
                inp = payload.get("arguments") or payload.get("input") or {}
                if payload.get("command") and not inp:
                    inp = {"command": payload.get("command")}
                yield {"type": "tool_use_start", "id": tid, "name": name}
                yield {"type": "tool_use_end", "id": tid, "name": name, "input": inp}
                command_tools[tid] = {
                    "type": "tool_use", "id": tid, "name": name, "input": inp,
                }
                content.append(command_tools[tid])
            elif etype == "token_usage":
                usage_in = int(payload.get("input_tokens", 0) or 0)
                usage_out = int(payload.get("output_tokens", 0) or 0)
            elif etype == "error":
                err = payload.get("message") or str(payload)
                if not _ignore_codex_error(str(err)):
                    text = f"\n_Codex error: {err}_"
                    record_text(text)
                    yield {"type": "text_delta", "text": text}

        await proc.wait()
        if proc.returncode and proc.returncode != 0:
            err_blob = (await proc.stderr.read()).decode("utf-8", errors="replace")[-400:]
            if err_blob.strip():
                text = f"\n_codex exited {proc.returncode}: {err_blob}_"
                record_text(text)
                yield {"type": "text_delta", "text": text}

        for tid, block in command_tools.items():
            if tid in command_results:
                continue
            result = {
                "kind": "codex_command_result",
                "command": block.get("input", {}).get("command", ""),
                "status": "unknown",
                "exit_code": None,
                "output": "Codex ended before reporting this command result.",
            }
            command_results.add(tid)
            yield {
                "type": "tool_use_result",
                "id": tid,
                "name": block.get("name", "codex_command"),
                "result": result,
            }

        yield {
            "type": "turn_end",
            # Codex CLI runs its own tools before returning. Mark the turn as
            # complete so Puffin's registry doesn't try to invoke local names
            # like `codex_command`.
            "stop_reason": "end_turn",
            "usage": {"input_tokens": usage_in, "output_tokens": usage_out},
                "content": content,
        }


def _command_tool(item: dict[str, Any], fallback_index: int) -> tuple[str, str, dict[str, Any]]:
    tid = str(item.get("id") or f"codex_command_{fallback_index}")
    command = str(item.get("command") or "")
    return tid, "codex_command", {"command": command}


def _command_result(item: dict[str, Any]) -> dict[str, Any]:
    output = (
        item.get("aggregated_output")
        if item.get("aggregated_output") is not None
        else item.get("output")
    )
    if output is None:
        output = item.get("stdout") or item.get("stderr") or ""
    exit_code = item.get("exit_code")
    status = str(item.get("status") or "completed")
    return {
        "kind": "codex_command_result",
        "command": str(item.get("command") or ""),
        "status": status,
        "exit_code": exit_code,
        "ok": status == "completed" and exit_code == 0,
        "output": str(output),
    }


def _ignore_codex_error(message: str) -> bool:
    return message.startswith("Ignoring malformed agent role definition:")


def _messages_to_prompt(messages: list[dict[str, Any]]) -> str:
    """Same trick as ClaudeCodeProvider — flatten history into a prompt."""
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
        return "<conversation_history>\n" + "\n".join(parts) + "\n</conversation_history>\n\n" + new_msg
    return new_msg
