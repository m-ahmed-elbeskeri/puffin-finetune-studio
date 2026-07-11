"""Shared inference pipeline used by all serving entrypoints.

Pipeline:
    request → input guardrails → build canonical messages (shared with training)
            → backend.generate → output guardrails + post-process → response

Returns a `PipelineResult` with text + telemetry. The HTTP layer wraps this
into the OpenAI-compatible response shape.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

from llmops.features.prompt_builder import PROMPT_BUILDER_VERSION
from llmops.features.schemas import (
    ChatChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    Message,
    Role,
    Usage,
)
from llmops.serving.backends import Backend
from llmops.serving.guardrails import GuardrailConfig, check_input, check_output
from llmops.serving.postprocess import strip_code_fences, truncate_at_stop


@dataclass
class PipelineResult:
    response: ChatCompletionResponse
    request_id: str
    backend: str
    model_version: str
    latency_ms: float
    input_tokens: int
    output_tokens: int


def run_chat_completion(
    request: ChatCompletionRequest,
    *,
    backend: Backend,
    guardrails: GuardrailConfig,
    request_id: str | None = None,
    strip_fences_on_json: bool = True,
) -> PipelineResult:
    rid = request_id or f"req_{uuid.uuid4().hex[:24]}"
    t_start = time.perf_counter()

    check_input(request.messages, guardrails)

    messages: list[Message] = list(request.messages)

    gen = backend.generate(
        messages,
        max_tokens=request.max_tokens or 256,
        temperature=request.temperature,
        top_p=request.top_p,
        stop=request.stop,
        seed=request.seed,
    )

    text = gen.text
    if request.stop:
        text = truncate_at_stop(text, request.stop)
    if (
        strip_fences_on_json
        and request.response_format
        and request.response_format.get("type") == "json_object"
    ):
        text = strip_code_fences(text)

    text = check_output(text, guardrails)

    total_latency = (time.perf_counter() - t_start) * 1000.0
    response = ChatCompletionResponse(
        id=rid,
        created=int(time.time()),
        model=request.model,
        choices=[
            ChatChoice(
                index=0,
                message=Message(role=Role.ASSISTANT, content=text),
                finish_reason=gen.finish_reason if gen.finish_reason in {"stop", "length", "content_filter", "tool_calls"} else "stop",
            )
        ],
        usage=Usage(
            prompt_tokens=gen.input_tokens,
            completion_tokens=gen.output_tokens,
            total_tokens=gen.input_tokens + gen.output_tokens,
        ),
        system_fingerprint=backend.model_version,
        puffin_metadata={
            "backend": backend.name,
            "model_version": backend.model_version,
            "prompt_builder_version": PROMPT_BUILDER_VERSION,
            "request_id": rid,
        },
    )
    return PipelineResult(
        response=response,
        request_id=rid,
        backend=backend.name,
        model_version=backend.model_version,
        latency_ms=total_latency,
        input_tokens=gen.input_tokens,
        output_tokens=gen.output_tokens,
    )


def coerce_request(payload: dict[str, Any]) -> ChatCompletionRequest:
    """Validate + coerce a raw dict (e.g. from FastAPI) into ChatCompletionRequest."""
    return ChatCompletionRequest.model_validate(payload)
