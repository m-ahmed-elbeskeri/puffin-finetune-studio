"""OpenAICodexProvider — drives OpenAI's Codex-style models (gpt-5, gpt-5-codex).

Implements the same StreamEvent protocol Anthropic + ClaudeCode use, so the
copilot's chat loop, frontend, and persistence are provider-agnostic.

The tools shipped to OpenAI are the same Pydantic-typed Puffin tools, mapped
to OpenAI's `functions` schema. The loop layer (copilot.backend.loop) handles
the tool_use → tool_result round-trip; this provider only emits events from
ONE assistant turn (text deltas + completed tool calls).

Message format translation:
- We receive Anthropic-shaped messages from the loop (content blocks).
- OpenAI expects flat `{role, content}` for text + `{role, content, tool_calls}`
  for assistant turns that called tools + `{role: "tool", content, tool_call_id}`
  for results. We translate inline in `_to_openai_messages`.
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator


def _to_openai_tools() -> list[dict[str, Any]]:
    """Map our typed-tool registry to OpenAI's `tools=[{type:"function",...}]`."""
    from copilot.backend.tools import registry

    out: list[dict[str, Any]] = []
    for td in registry.all():
        schema = td.args_model.model_json_schema()
        schema.pop("title", None)
        # OpenAI requires `parameters` with type=object — we always have that
        # because Pydantic always emits an object root.
        out.append({
            "type": "function",
            "function": {
                "name": td.name,
                "description": td.description,
                "parameters": schema,
            },
        })
    return out


def _to_openai_messages(
    system: str | None,
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Anthropic-shaped → OpenAI-shaped.

    Mapping rules:
      user/text                  → {role: "user", content: text}
      user/tool_result           → {role: "tool", tool_call_id, content}
      assistant/text             → {role: "assistant", content: text}
      assistant/tool_use         → {role: "assistant", tool_calls: [...]}
    """
    out: list[dict[str, Any]] = []
    if system:
        out.append({"role": "system", "content": system})

    for m in messages:
        role = m.get("role")
        content_blocks = m.get("content") or []

        if role == "user":
            # User messages may carry text OR tool_result blocks (per the
            # Anthropic protocol Claude uses). Tool results become role=tool.
            text_parts: list[str] = []
            for b in content_blocks:
                btype = b.get("type")
                if btype == "text":
                    text_parts.append(b.get("text", ""))
                elif btype == "tool_result":
                    out.append({
                        "role": "tool",
                        "tool_call_id": b.get("tool_use_id"),
                        "content": str(b.get("content", "")),
                    })
            if text_parts:
                out.append({"role": "user",
                            "content": "\n".join(text_parts)})

        elif role == "assistant":
            text_parts = []
            tool_calls: list[dict[str, Any]] = []
            for b in content_blocks:
                btype = b.get("type")
                if btype == "text":
                    text_parts.append(b.get("text", ""))
                elif btype == "tool_use":
                    tool_calls.append({
                        "id": b.get("id"),
                        "type": "function",
                        "function": {
                            "name": b.get("name"),
                            "arguments": json.dumps(b.get("input") or {}),
                        },
                    })
            asst: dict[str, Any] = {"role": "assistant"}
            if text_parts:
                asst["content"] = "\n".join(text_parts)
            else:
                asst["content"] = None
            if tool_calls:
                asst["tool_calls"] = tool_calls
            out.append(asst)

    return out


class OpenAICodexProvider:
    """OpenAI chat completions provider, configured for Codex-class models.

    Default model is `gpt-5-codex` (set via env or thread.model); falls back
    to `gpt-5` if Codex isn't enabled on the account. Any chat-completions
    model with function-calling works.
    """

    name = "openai_codex"

    def __init__(
        self,
        api_key: str,
        *,
        client: Any | None = None,
        default_model: str = "gpt-5-codex",
    ) -> None:
        self._default_model = default_model
        if client is not None:
            self._client = client
        else:
            from openai import AsyncOpenAI
            if not api_key:
                raise ValueError("OPENAI_API_KEY required for OpenAICodexProvider")
            self._client = AsyncOpenAI(api_key=api_key)

    async def stream_turn(
        self,
        *,
        model: str,
        system: str | None,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],     # noqa: ARG002 — built from our registry
        max_tokens: int,
        tool_ctx: Any = None,  # noqa: ARG002 — the loop dispatches tools itself
    ) -> AsyncIterator[dict[str, Any]]:
        oai_messages = _to_openai_messages(system, messages)
        oai_tools = _to_openai_tools()

        # State accumulated across stream deltas.
        text_chunks: list[str] = []
        # Tool-call accumulator keyed by index (OpenAI streams tool_call
        # arguments incrementally as JSON fragments).
        tool_calls: dict[int, dict[str, Any]] = {}
        announced_starts: set[int] = set()
        finish_reason = "stop"
        usage_in = 0
        usage_out = 0

        # Pick the actual model: thread.model wins, fall back to default.
        chosen_model = model or self._default_model
        if chosen_model.startswith("openai:"):
            chosen_model = chosen_model[len("openai:"):]
        if chosen_model.startswith("codex:"):
            chosen_model = chosen_model[len("codex:"):] or self._default_model

        try:
            stream = await self._client.chat.completions.create(
                model=chosen_model,
                messages=oai_messages,
                tools=oai_tools if oai_tools else None,
                tool_choice="auto" if oai_tools else None,
                max_tokens=int(max_tokens),
                stream=True,
                stream_options={"include_usage": True},
            )
        except Exception as exc:  # noqa: BLE001
            # Surface as a final text block + clean turn_end so the loop can
            # persist + close instead of dying.
            err = f"OpenAI request failed: {type(exc).__name__}: {exc}"
            yield {"type": "text_delta", "text": err}
            yield {
                "type": "turn_end", "stop_reason": "end_turn",
                "usage": {"input_tokens": 0, "output_tokens": 0},
                "content": [{"type": "text", "text": err}],
            }
            return

        async for event in stream:
            choices = getattr(event, "choices", None) or []
            usage = getattr(event, "usage", None)
            if usage is not None:
                usage_in = int(getattr(usage, "prompt_tokens", 0) or 0)
                usage_out = int(getattr(usage, "completion_tokens", 0) or 0)
            if not choices:
                continue
            choice = choices[0]
            delta = getattr(choice, "delta", None)
            if delta is None:
                continue

            # Text deltas
            text = getattr(delta, "content", None)
            if text:
                text_chunks.append(text)
                yield {"type": "text_delta", "text": text}

            # Tool call deltas — fragments of JSON args arrive across chunks.
            tcs = getattr(delta, "tool_calls", None) or []
            for tc in tcs:
                idx = int(getattr(tc, "index", 0) or 0)
                slot = tool_calls.setdefault(idx, {
                    "id": None, "name": None, "args_buf": [],
                })
                tc_id = getattr(tc, "id", None)
                if tc_id and not slot["id"]:
                    slot["id"] = tc_id
                fn = getattr(tc, "function", None)
                if fn is not None:
                    name = getattr(fn, "name", None)
                    if name and not slot["name"]:
                        slot["name"] = name
                    args = getattr(fn, "arguments", None) or ""
                    if args:
                        slot["args_buf"].append(args)

                # Once we have the id + name and haven't announced yet, fire start.
                if (
                    slot["id"] and slot["name"]
                    and idx not in announced_starts
                ):
                    announced_starts.add(idx)
                    yield {
                        "type": "tool_use_start",
                        "id": slot["id"], "name": slot["name"],
                    }

            fr = getattr(choice, "finish_reason", None)
            if fr:
                finish_reason = fr

        # End-of-stream: finalize each tool_call's args and emit tool_use_end.
        assembled: list[dict[str, Any]] = []
        if text_chunks:
            assembled.append({"type": "text", "text": "".join(text_chunks)})
        for idx in sorted(tool_calls):
            slot = tool_calls[idx]
            raw = "".join(slot["args_buf"])
            try:
                args = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                args = {"_raw": raw, "_parse_error": True}
            assembled.append({
                "type": "tool_use",
                "id": slot["id"], "name": slot["name"], "input": args,
            })
            yield {
                "type": "tool_use_end",
                "id": slot["id"], "name": slot["name"], "input": args,
            }

        stop_reason = "tool_use" if finish_reason == "tool_calls" else "end_turn"
        yield {
            "type": "turn_end", "stop_reason": stop_reason,
            "usage": {"input_tokens": usage_in, "output_tokens": usage_out},
            "content": assembled,
        }
