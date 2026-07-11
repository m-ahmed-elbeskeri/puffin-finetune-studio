"""ClaudeCodeProvider — uses the local Claude Code CLI via claude-agent-sdk.

Why offer this on top of the raw Anthropic API?
- Claude Code already has Bash, Read, Edit, Glob, Grep, etc. — useful for ad-hoc
  exploration the user might want during a chat ("show me the diff", "grep for
  X", "what's in this file?").
- Our 24 Puffin tools are exposed to Claude Code as an in-process MCP server
  (`mcp__puffin__*`), so the model can call them seamlessly alongside its built-ins.
- The chat session uses the user's local Claude Code install — no API key needed
  beyond what the CLI itself already has.

Conversation continuity: our SQLite owns the canonical history. Each turn we
flatten prior messages into a `<conversation_history>` prefix on the prompt and
hand it to claude_agent_sdk.query(). Claude Code's own session state is not used.
"""
from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator

from copilot.backend.tools import ToolContext, registry


@dataclass
class _MCPRecord:
    """Bridge MCP handler invocations back to the provider's event stream.

    The SDK runs MCP tools internally and may not emit a UserMessage with
    the ToolResultBlock before continuing. We capture the result in the
    handler and pair it (by call order) with the tool_use_id we observed
    on the prior ToolUseBlock.

    `halt` is set when a tool returns `awaiting_user_input: true`; the
    provider checks this after every SDK message and breaks out of the
    `async for query()` loop so the SDK doesn't keep talking over the
    user-input request.
    """
    pending_ids: deque[str] = field(default_factory=deque)
    results: deque[dict[str, Any]] = field(default_factory=deque)
    halt: bool = False

    def drain(self) -> list[tuple[str, dict[str, Any]]]:
        out: list[tuple[str, dict[str, Any]]] = []
        while self.pending_ids and self.results:
            out.append((self.pending_ids.popleft(), self.results.popleft()))
        return out


def _build_mcp_server(ctx: ToolContext, record: _MCPRecord | None = None):
    """Wrap every Puffin tool as an SDK-MCP tool the Claude Code CLI can call.

    claude-agent-sdk's `tool(name, description, input_schema)` accepts a full
    JSON Schema dict for `input_schema` — we pass the Pydantic-generated one
    so constraints (ge/le, defaults, enums) survive into Claude's view.
    The result shape `{"content": [...], "is_error": bool}` is per the
    Anthropic MCP tool-result contract.
    """
    from claude_agent_sdk import create_sdk_mcp_server, tool as sdk_tool

    wrapped: list[Any] = []
    for td in registry.all():
        try:
            input_schema = td.args_model.model_json_schema()
            input_schema.pop("title", None)
        except Exception:  # noqa: BLE001
            input_schema = {"type": "object", "properties": {}}

        # Closure over `td` so each wrapper invokes the right tool. Also
        # pushes the raw result into the shared record so the provider's
        # event stream can pair it with the matching tool_use_id.
        async def _handler(args: dict[str, Any], _td=td) -> dict[str, Any]:
            result = await registry.invoke(_td.name, args or {}, ctx)
            if record is not None:
                record.results.append(result)
                # Tools like ask_user_question signal the loop should pause
                # for the human; the provider breaks out of the SDK iterator
                # so the next assistant turn never starts.
                if result.get("awaiting_user_input"):
                    record.halt = True
            is_error = result.get("kind") == "error"
            return {
                "content": [
                    {"type": "text", "text": json.dumps(result, default=str)},
                ],
                **({"is_error": True} if is_error else {}),
            }

        wrapped.append(sdk_tool(
            td.name,
            td.description,
            input_schema,
        )(_handler))

    return create_sdk_mcp_server("puffin", "0.1.0", wrapped)


def _messages_to_prompt(messages: list[dict[str, Any]]) -> str:
    """Flatten our stored conversation into a single Claude Code prompt.

    Claude Code's query() takes a string prompt; multi-turn continuity is the
    caller's job. We embed prior turns inside <conversation_history> so the
    model can refer back without us needing to wire its session machinery.
    """
    if not messages:
        return ""
    parts: list[str] = []
    *history, last = messages
    for m in history:
        role = m.get("role")
        for block in m.get("content", []) or []:
            btype = block.get("type")
            if role == "user" and btype == "text":
                parts.append(f"[prev user] {block.get('text', '')}")
            elif role == "user" and btype == "tool_result":
                body = str(block.get("content", ""))[:400]
                parts.append(f"[prev tool_result] {body}")
            elif role == "assistant" and btype == "text":
                parts.append(f"[you earlier] {block.get('text', '')}")
            elif role == "assistant" and btype == "tool_use":
                args = json.dumps(block.get("input", {}), default=str)[:200]
                parts.append(
                    f"[you earlier called] {block.get('name', '?')}({args})"
                )

    new_msg = ""
    for block in last.get("content", []) or []:
        if block.get("type") == "text":
            new_msg += block.get("text", "")

    if parts:
        prefix = (
            "<conversation_history>\n" + "\n".join(parts)
            + "\n</conversation_history>\n\n"
        )
    else:
        prefix = ""
    return prefix + new_msg


class ClaudeCodeProvider:
    """Drives a local Claude Code session via claude-agent-sdk."""

    name = "claude_code"

    def __init__(
        self,
        *,
        repo_root: str | None = None,
        enable_dangerous: bool = False,
    ) -> None:
        from pathlib import Path
        self.repo_root = Path(repo_root) if repo_root else Path.cwd()
        self.enable_dangerous = enable_dangerous

    async def stream_turn(
        self,
        *,
        model: str,
        system: str | None,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],  # noqa: ARG002 — Claude Code uses its own + MCP
        max_tokens: int,                # noqa: ARG002 — controlled by the CLI
        tool_ctx: ToolContext | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        from claude_agent_sdk import (
            AssistantMessage, ClaudeAgentOptions, ResultMessage,
            StreamEvent, TextBlock, ToolResultBlock, ToolUseBlock,
            UserMessage, query,
        )

        # Scope to the chat thread's project. Without this the MCP tools (and
        # the CLI's own cwd) run against the provider's startup repo_root,
        # editing the WRONG project when the user is on a different one.
        ctx = tool_ctx or ToolContext(
            repo_root=self.repo_root, enable_dangerous=self.enable_dangerous,
        )
        run_root = Path(ctx.repo_root)
        record = _MCPRecord()
        mcp = _build_mcp_server(ctx, record)
        prompt = _messages_to_prompt(messages)
        if not prompt.strip():
            yield {
                "type": "turn_end", "stop_reason": "end_turn",
                "usage": {"input_tokens": 0, "output_tokens": 0},
                "content": [{"type": "text", "text": ""}],
            }
            return

        # MCP tool names land as `mcp__puffin__<name>` — allow them all, plus
        # the built-in read-only tools by default.
        dangerous = ctx.enable_dangerous
        allowed = ["mcp__puffin__*", "Read", "Glob", "Grep", "WebFetch", "WebSearch"]
        if dangerous:
            allowed += ["Bash", "Write", "Edit", "NotebookEdit"]

        options = ClaudeAgentOptions(
            cwd=str(run_root),
            mcp_servers={"puffin": mcp},
            allowed_tools=allowed,
            permission_mode="bypassPermissions" if dangerous else "default",
            system_prompt=system,
            model=model if model and model != "default" else None,
            max_turns=10,
            # True so we get per-token streaming deltas instead of whole
            # text blocks — frontend renders the cursor-blink reply live.
            include_partial_messages=True,
            # Load the user's installed skills (~/.claude/skills/) AND the
            # project-level ones (./.claude/skills/). 'all' tells the SDK to
            # let Claude pick by name+description — including the existing
            # `puffin-finetune` skill the user already wrote.
            setting_sources=["user", "project"],
            skills="all",
        )

        assembled: list[dict[str, Any]] = []
        usage_in = 0
        usage_out = 0
        stop_reason = "end_turn"
        # Content-block indexes whose text we already streamed via
        # StreamEvent deltas. When the final AssistantMessage arrives we
        # skip yielding their text again to avoid duplicates.
        streamed_text_indexes: set[int] = set()
        streamed_tool_indexes: dict[int, dict[str, Any]] = {}
        streamed_tool_ids: set[str] = set()

        try:
            async for msg in query(prompt=prompt, options=options):
                if isinstance(msg, StreamEvent):
                    # Partial-message stream: per-token text deltas from
                    # the Anthropic Messages streaming API, plus block
                    # start/stop markers. Forward tool_use markers too so
                    # the frontend shows live tool activity immediately.
                    raw = getattr(msg, "event", None) or {}
                    etype = raw.get("type")
                    if etype == "content_block_start":
                        block = raw.get("content_block") or {}
                        idx = int(raw.get("index", -1))
                        if block.get("type") == "text":
                            streamed_text_indexes.add(idx)
                        elif block.get("type") == "tool_use":
                            tid = block.get("id")
                            name = block.get("name", "") or ""
                            display_name = name
                            if name.startswith("mcp__puffin__"):
                                display_name = name[len("mcp__puffin__"):]
                            streamed_tool_indexes[idx] = {
                                "id": tid, "name": display_name, "args": [],
                            }
                            if tid:
                                streamed_tool_ids.add(tid)
                            yield {
                                "type": "tool_use_start",
                                "id": tid, "name": display_name,
                            }
                    elif etype == "content_block_delta":
                        idx = int(raw.get("index", -1))
                        delta = raw.get("delta") or {}
                        if delta.get("type") == "text_delta":
                            chunk = delta.get("text") or ""
                            if chunk:
                                yield {"type": "text_delta", "text": chunk}
                        elif delta.get("type") == "input_json_delta":
                            slot = streamed_tool_indexes.get(idx)
                            if slot is not None:
                                slot["args"].append(delta.get("partial_json") or "")
                    elif etype == "content_block_stop":
                        idx = int(raw.get("index", -1))
                        slot = streamed_tool_indexes.get(idx)
                        if slot is not None:
                            raw_args = "".join(slot.get("args") or [])
                            try:
                                parsed_args = json.loads(raw_args) if raw_args else {}
                            except json.JSONDecodeError:
                                parsed_args = {
                                    "_raw": raw_args, "_parse_error": True,
                                }
                            yield {
                                "type": "tool_use_end",
                                "id": slot.get("id"),
                                "name": slot.get("name"),
                                "input": parsed_args,
                            }
                    # content_block_stop / message_delta etc. — nothing
                    # to yield; the final AssistantMessage will carry the
                    # authoritative content list shortly.
                    continue

                if isinstance(msg, AssistantMessage):
                    for idx, block in enumerate(getattr(msg, "content", None) or []):
                        if isinstance(block, TextBlock):
                            text = getattr(block, "text", "") or ""
                            assembled.append({"type": "text", "text": text})
                            # Only yield as one chunk if the streaming
                            # path didn't already deliver this block —
                            # otherwise the frontend duplicates the text.
                            if idx not in streamed_text_indexes:
                                yield {"type": "text_delta", "text": text}
                        elif isinstance(block, ToolUseBlock):
                            tid = getattr(block, "id", None)
                            name = getattr(block, "name", "") or ""
                            inp = getattr(block, "input", {}) or {}
                            # Strip the `mcp__puffin__` prefix for display.
                            display_name = name
                            if name.startswith("mcp__puffin__"):
                                display_name = name[len("mcp__puffin__"):]
                            assembled.append({
                                "type": "tool_use", "id": tid,
                                "name": display_name, "input": inp,
                            })
                            # Track this id so the MCP-handler result can
                            # be paired back to it after the SDK runs.
                            if tid:
                                record.pending_ids.append(tid)
                            if tid not in streamed_tool_ids:
                                yield {
                                    "type": "tool_use_start",
                                    "id": tid, "name": display_name,
                                }
                                yield {
                                    "type": "tool_use_end",
                                    "id": tid, "name": display_name, "input": inp,
                                }
                elif isinstance(msg, UserMessage):
                    # Claude Code SDK already ran the tool via the in-process
                    # MCP server and is echoing the result back. We forward
                    # it as `tool_use_result` so the loop emits the SSE
                    # `tool_result` event and the frontend's pending card
                    # finally flips to "done" with its real artifact.
                    for block in (getattr(msg, "content", None) or []):
                        if not isinstance(block, ToolResultBlock):
                            continue
                        tu_id = getattr(block, "tool_use_id", None)
                        raw = getattr(block, "content", None) or []
                        text_parts: list[str] = []
                        if isinstance(raw, str):
                            text_parts.append(raw)
                        elif isinstance(raw, list):
                            for c in raw:
                                if isinstance(c, dict):
                                    text_parts.append(c.get("text", "") or "")
                                else:
                                    t = getattr(c, "text", None)
                                    if t:
                                        text_parts.append(t)
                        text = "".join(text_parts)
                        try:
                            result = json.loads(text) if text else {}
                            if not isinstance(result, dict):
                                result = {"kind": "raw", "value": result}
                        except json.JSONDecodeError:
                            result = {
                                "kind": "error",
                                "message": text[:1000] or "empty tool result",
                            }
                        yield {
                            "type": "tool_use_result",
                            "id": tu_id,
                            "result": result,
                        }
                elif isinstance(msg, ResultMessage):
                    sr = getattr(msg, "subtype", None) or "end_turn"
                    stop_reason = (
                        "end_turn" if sr in ("success", "end_turn") else sr
                    )
                    usage = getattr(msg, "usage", None) or {}
                    if isinstance(usage, dict):
                        usage_in = int(usage.get("input_tokens") or 0)
                        usage_out = int(usage.get("output_tokens") or 0)

                # After every SDK message, flush any MCP-handler results
                # that have completed since the last drain — pair each
                # with the earliest unmatched tool_use_id.
                for tid, res in record.drain():
                    yield {
                        "type": "tool_use_result", "id": tid, "result": res,
                    }
                # Halt the SDK if a tool signalled awaiting_user_input.
                # Without this the SDK keeps streaming the next assistant
                # turn over the interactive card the frontend just rendered.
                # Breaking the `async for` calls aclose() on the generator,
                # which cancels any pending subprocess work in the SDK.
                if record.halt:
                    stop_reason = "awaiting_user_input"
                    break
        except Exception as exc:  # noqa: BLE001
            err = f"\n\n_Claude Code error: {type(exc).__name__}: {exc}_"
            yield {"type": "text_delta", "text": err}
            # Mirror into assembled so the persisted assistant message
            # keeps the error text after a thread refetch.
            assembled.append({"type": "text", "text": err})

        # Final drain — catch results that landed after the last message.
        for tid, res in record.drain():
            yield {"type": "tool_use_result", "id": tid, "result": res}

        yield {
            "type": "turn_end", "stop_reason": stop_reason,
            "usage": {"input_tokens": usage_in, "output_tokens": usage_out},
            "content": assembled,
        }
