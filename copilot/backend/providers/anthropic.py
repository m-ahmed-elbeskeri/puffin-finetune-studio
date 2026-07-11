"""Anthropic provider — streams Messages API + emits provider-agnostic events.

Uses the official `anthropic` SDK's async streaming. Translates SSE events
into the stream protocol defined in providers/base.py.
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, *, client: Any | None = None) -> None:
        if client is not None:
            self._client = client
        else:
            try:
                from anthropic import AsyncAnthropic
            except ImportError as e:  # pragma: no cover
                raise ImportError(
                    "anthropic SDK not installed. "
                    'Run: pip install -e ".[copilot]"'
                ) from e
            if not api_key:
                raise ValueError(
                    "ANTHROPIC_API_KEY is required to use the Anthropic provider."
                )
            self._client = AsyncAnthropic(api_key=api_key)

    async def stream_turn(
        self,
        *,
        model: str,
        system: str | None,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
        tool_ctx: Any = None,  # noqa: ARG002 — the loop dispatches tools itself
    ) -> AsyncIterator[dict[str, Any]]:
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": int(max_tokens),
            "messages": messages,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools

        # Final-state we assemble as we stream.
        content_blocks: list[dict[str, Any]] = []
        cur_block_idx: int = -1
        cur_tool_use_input_buf: dict[int, list[str]] = {}
        cur_text_buf: dict[int, list[str]] = {}
        usage_in = 0
        usage_out = 0
        stop_reason = "end_turn"

        async with self._client.messages.stream(**kwargs) as stream:
            async for evt in stream:
                etype = getattr(evt, "type", None)

                if etype == "message_start":
                    msg = getattr(evt, "message", None)
                    if msg is not None:
                        usage = getattr(msg, "usage", None)
                        if usage is not None:
                            usage_in = int(getattr(usage, "input_tokens", 0) or 0)

                elif etype == "content_block_start":
                    cur_block_idx = int(getattr(evt, "index", 0) or 0)
                    block = getattr(evt, "content_block", None)
                    btype = getattr(block, "type", None) if block else None
                    if btype == "text":
                        content_blocks.append({"type": "text", "text": ""})
                        cur_text_buf[cur_block_idx] = []
                    elif btype == "tool_use":
                        tu_id = getattr(block, "id", None)
                        tu_name = getattr(block, "name", None)
                        content_blocks.append({
                            "type": "tool_use", "id": tu_id, "name": tu_name, "input": {},
                        })
                        cur_tool_use_input_buf[cur_block_idx] = []
                        yield {
                            "type": "tool_use_start",
                            "id": tu_id, "name": tu_name,
                            "input_partial": "",
                        }

                elif etype == "content_block_delta":
                    idx = int(getattr(evt, "index", 0) or 0)
                    delta = getattr(evt, "delta", None)
                    dtype = getattr(delta, "type", None) if delta else None
                    if dtype == "text_delta":
                        text = getattr(delta, "text", "") or ""
                        cur_text_buf.setdefault(idx, []).append(text)
                        yield {"type": "text_delta", "text": text}
                    elif dtype == "input_json_delta":
                        partial = getattr(delta, "partial_json", "") or ""
                        cur_tool_use_input_buf.setdefault(idx, []).append(partial)
                        block = content_blocks[idx]
                        yield {
                            "type": "tool_use_delta",
                            "id": block.get("id"),
                            "input_partial": partial,
                        }

                elif etype == "content_block_stop":
                    idx = int(getattr(evt, "index", 0) or 0)
                    if 0 <= idx < len(content_blocks):
                        block = content_blocks[idx]
                        if block.get("type") == "text":
                            block["text"] = "".join(cur_text_buf.get(idx, []))
                        elif block.get("type") == "tool_use":
                            raw = "".join(cur_tool_use_input_buf.get(idx, []))
                            try:
                                block["input"] = json.loads(raw) if raw else {}
                            except json.JSONDecodeError:
                                block["input"] = {"_raw": raw, "_parse_error": True}
                            yield {
                                "type": "tool_use_end",
                                "id": block.get("id"),
                                "name": block.get("name"),
                                "input": block["input"],
                            }

                elif etype == "message_delta":
                    delta = getattr(evt, "delta", None)
                    sr = getattr(delta, "stop_reason", None) if delta else None
                    if sr:
                        stop_reason = sr
                    usage = getattr(evt, "usage", None)
                    if usage is not None:
                        usage_out = int(getattr(usage, "output_tokens", 0) or 0)

                elif etype == "message_stop":
                    # final usage may also be on the assembled message
                    final = await stream.get_final_message() if hasattr(
                        stream, "get_final_message") else None
                    if final is not None:
                        u = getattr(final, "usage", None)
                        if u is not None:
                            usage_in = int(getattr(u, "input_tokens", usage_in) or usage_in)
                            usage_out = int(getattr(u, "output_tokens", usage_out) or usage_out)
                        sr = getattr(final, "stop_reason", None)
                        if sr:
                            stop_reason = sr

        yield {
            "type": "turn_end",
            "stop_reason": stop_reason,
            "usage": {"input_tokens": usage_in, "output_tokens": usage_out},
            "content": content_blocks,
        }
