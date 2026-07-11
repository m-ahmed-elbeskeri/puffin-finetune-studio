"""Tool-use multi-turn loop.

Drives a Provider through:
    user → assistant (possibly tool_use) → tool_result → assistant → ... → end_turn

Emits one stream of provider-agnostic events that the FastAPI app
encodes as Server-Sent Events to the frontend.

Event types (one of these per yield):
    {"event": "text",         "data": {"text": "..."}}
    {"event": "tool_call",    "data": {"id", "name", "input"}}
    {"event": "tool_result",  "data": {"id", "name", "result"}}
    {"event": "usage",        "data": {"input_tokens", "output_tokens",
                                       "cumulative_input", "cumulative_output"}}
    {"event": "assistant_message", "data": {"content": [...]}}
    {"event": "done",         "data": {"stop_reason": "..."}}
    {"event": "error",        "data": {"message": "..."}}

A turn (one user input → final end_turn) may contain multiple provider
iterations because of tool_use → tool_result → tool_use chains. The loop
is bounded by `max_iterations` to defend against runaway agents.
"""
from __future__ import annotations

from typing import Any, AsyncIterator

from copilot.backend.providers.base import Provider
from copilot.backend.tools import ToolContext, registry


DEFAULT_SYSTEM_PROMPT = """You are the Puffin Studio copilot, an expert LLM fine-tuning \
engineer embedded in the Puffin platform.

Your job is to help the user get a model trained, evaluated, deployed, and \
monitored — the user should be able to do EVERYTHING through you, at any \
skill level. You have direct tool access to the platform: project_status, \
dataset_audit, dataset_preview, dataset_list, dataset_import_hf, \
data_pipeline_run, train_studio_recipes, train_studio_launch, train_start, \
train_status, train_history, train_get_run, train_cancel, eval_run, \
gate_apply, eval_get_metrics, deploy_push, deploy_promote, deploy_render_k8s, \
registry_list, serve_health, serve_chat, monitor_request_log, monitor_quality, \
monitor_drift, config_list, config_read, config_edit.

For training with specific settings, prefer train_studio_launch (recipe \
and/or dotted knob overrides on top of the base config; call \
train_studio_recipes first to see options and current values) over hand-editing \
YAML with config_edit. When the user's ask is vague ("make it better at X"), \
pick a recipe, explain your choice in one sentence, and smoke-test it.

Rules:
1. ALWAYS call project_status at the start of a fresh conversation so your \
suggestions are grounded in the actual project state.
2. For any first training run on a new dataset/config, ALWAYS smoke=true \
first. Real (smoke=false) training only after the smoke passes.
3. When the user asks a "what should I do" question, propose the ONE next \
concrete action with the exact tool you would call. Don't enumerate every \
possibility.
3a. When a decision has a real branch (smoke vs full train, which adapter, \
which dataset, what threshold), call `ask_user_question` instead of \
guessing — STOP after that call and wait for the answer.
4. Surface costs/timings before doing anything expensive. dataset_audit / \
project_status give you the inputs you need.
5. When a tool returns kind=*_result or *_card, the frontend renders it as a \
custom card. Don't restate its contents — comment on what it MEANS for the \
user's goal.
6. If a destructive tool returns an error about being disabled, tell the user \
how to enable it (PUFFIN_COPILOT_ENABLE_DANGEROUS=1) — don't try to work around \
it.

Stay terse. The user is technical."""


async def run_loop(
    *,
    provider: Provider,
    model: str,
    system: str | None,
    messages: list[dict[str, Any]],
    tool_ctx: ToolContext,
    max_tokens: int,
    max_iterations: int = 10,
) -> AsyncIterator[dict[str, Any]]:
    """Multi-turn tool-use loop. Mutates `messages` in place as it runs so
    the caller can persist the final state to the thread store."""
    sys_prompt = system or DEFAULT_SYSTEM_PROMPT
    tools_schema = registry.to_anthropic_schemas()

    cumulative_in = 0
    cumulative_out = 0

    for iteration in range(max_iterations):
        # Run one provider turn (may itself contain tool_use blocks).
        turn_content: list[dict[str, Any]] = []
        stop_reason = "end_turn"
        turn_in = 0
        turn_out = 0
        # Tool-use ids the PROVIDER already executed (Claude Code SDK / Codex
        # CLI). We forward their results as-is and skip our own dispatch.
        provider_resolved: set[str] = set()
        # Parallel list of tool_result blocks for provider-resolved tools.
        # Appended to messages so a refreshed thread can reconstruct the
        # assistant's tool_use → user's tool_result pair (otherwise the
        # frontend's setFromStored leaves the tool stuck in "calling…").
        provider_resolved_blocks: list[dict[str, Any]] = []
        # Set if any provider-resolved tool returned awaiting_user_input
        # (e.g. ask_user_question). Halts the multi-iteration loop so the
        # interactive card stays the last thing on screen.
        provider_awaiting_user = False

        try:
            async for evt in provider.stream_turn(
                model=model, system=sys_prompt, messages=messages,
                tools=tools_schema, max_tokens=max_tokens,
                tool_ctx=tool_ctx,
            ):
                etype = evt.get("type")
                if etype == "text_delta":
                    yield {"event": "text", "data": {"text": evt.get("text", "")}}
                elif etype == "tool_use_start":
                    # The frontend uses this to render the "thinking" state
                    # for a tool call before the args arrive.
                    yield {
                        "event": "tool_call_start",
                        "data": {"id": evt.get("id"), "name": evt.get("name")},
                    }
                elif etype == "tool_use_end":
                    yield {
                        "event": "tool_call",
                        "data": {
                            "id": evt.get("id"),
                            "name": evt.get("name"),
                            "input": evt.get("input", {}),
                        },
                    }
                elif etype == "tool_use_result":
                    # Provider already ran the tool itself (Claude Code SDK
                    # via MCP, or Codex CLI). Forward the result so the
                    # frontend's pending card flips to "done" — and skip
                    # our own registry.invoke for this tool below.
                    import json as _json
                    tu_id = evt.get("id")
                    tu_result = evt.get("result", {}) or {}
                    # Some providers yield the same tool_use_result twice
                    # (once via drain(), once via UserMessage with
                    # ToolResultBlock). Dedupe so we don't double-emit
                    # frontend events or double-persist tool_result blocks.
                    if tu_id and tu_id in provider_resolved:
                        continue
                    yield {
                        "event": "tool_result",
                        "data": {
                            "id": tu_id,
                            "name": evt.get("name", ""),
                            "result": tu_result,
                        },
                    }
                    # Remember the id so we don't double-invoke after turn_end.
                    provider_resolved.add(tu_id)
                    # Build the matching tool_result block now so we can
                    # persist a protocol-correct conversation when the turn
                    # ends. Without this, the assistant's tool_use sits in
                    # storage with no paired tool_result and the frontend
                    # can't reconstruct the result card on refresh.
                    if tu_id:
                        provider_resolved_blocks.append({
                            "type": "tool_result",
                            "tool_use_id": tu_id,
                            "content": _json.dumps(tu_result, default=str),
                            "is_error": tu_result.get("kind") == "error",
                        })
                    if tu_result.get("awaiting_user_input"):
                        provider_awaiting_user = True
                elif etype == "turn_end":
                    turn_content = evt.get("content", [])
                    stop_reason = evt.get("stop_reason", "end_turn")
                    usage = evt.get("usage", {}) or {}
                    turn_in = int(usage.get("input_tokens", 0))
                    turn_out = int(usage.get("output_tokens", 0))
        except Exception as exc:  # noqa: BLE001
            yield {
                "event": "error",
                "data": {"message": f"{type(exc).__name__}: {exc}"},
            }
            return

        cumulative_in += turn_in
        cumulative_out += turn_out

        # Persist the assistant message into the conversation context.
        messages.append({"role": "assistant", "content": turn_content})
        yield {"event": "assistant_message", "data": {"content": turn_content}}
        yield {
            "event": "usage",
            "data": {
                "input_tokens": turn_in,
                "output_tokens": turn_out,
                "cumulative_input": cumulative_in,
                "cumulative_output": cumulative_out,
            },
        }

        # Persist tool_result blocks for tools the provider already ran
        # (MCP path) so the frontend's reconstruction sees a complete
        # tool_use → tool_result pair after a refresh.
        if provider_resolved_blocks:
            messages.append({
                "role": "user", "content": provider_resolved_blocks,
            })

        # If the model didn't request any tools, we're done.
        # Tools the provider already executed don't need re-dispatching.
        tool_uses = [
            b for b in turn_content
            if b.get("type") == "tool_use"
            and b.get("id") not in provider_resolved
        ]
        if stop_reason != "tool_use" or not tool_uses:
            # Halt with a distinct stop_reason when a provider-resolved
            # tool asked for user input — the frontend can show "awaiting
            # input" instead of "done" if useful.
            sr = "awaiting_user_input" if provider_awaiting_user else stop_reason
            yield {"event": "done", "data": {"stop_reason": sr}}
            return

        # Otherwise, run every requested tool and feed the results back.
        tool_result_blocks: list[dict[str, Any]] = []
        awaiting_user = False
        for tu in tool_uses:
            tu_id = tu.get("id")
            tu_name = tu.get("name", "")
            tu_input = tu.get("input", {}) or {}
            result = await registry.invoke(tu_name, tu_input, tool_ctx)
            yield {
                "event": "tool_result",
                "data": {"id": tu_id, "name": tu_name, "result": result},
            }
            # Anthropic expects content as a string for tool_result blocks;
            # we wrap the dict as JSON so it's both round-trippable and parseable
            # by the model.
            import json
            tool_result_blocks.append({
                "type": "tool_result",
                "tool_use_id": tu_id,
                "content": json.dumps(result, default=str),
                "is_error": result.get("kind") == "error",
            })
            if result.get("awaiting_user_input"):
                awaiting_user = True

        # Append a user message containing the tool_result blocks (per
        # Anthropic protocol), then loop back to the provider.
        messages.append({"role": "user", "content": tool_result_blocks})

        # Halt the loop if any tool signalled it needs user input — let the
        # frontend render the interactive card and wait for the next user
        # turn. We do NOT call the provider again; otherwise Claude will
        # either speak over the card or chain another tool that hides it.
        if awaiting_user:
            yield {
                "event": "done",
                "data": {"stop_reason": "awaiting_user_input"},
            }
            return

    yield {
        "event": "error",
        "data": {
            "message": (
                f"Tool-use loop hit the safety bound of {max_iterations} "
                "iterations. Tell the user the conversation may be stuck."
            ),
        },
    }
