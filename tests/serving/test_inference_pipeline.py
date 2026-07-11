from __future__ import annotations

from llmops.features.schemas import ChatCompletionRequest
from llmops.serving.backends import EchoBackend
from llmops.serving.guardrails import GuardrailConfig
from llmops.serving.inference_pipeline import (
    coerce_request,
    run_chat_completion,
)


def _req(messages, **kw) -> ChatCompletionRequest:
    payload = {"model": "test", "messages": messages, **kw}
    return ChatCompletionRequest.model_validate(payload)


def test_inference_pipeline_basic():
    backend = EchoBackend(rules=[("hello", "world")], default_response="?")
    req = _req([{"role": "user", "content": "hello there"}])
    result = run_chat_completion(req, backend=backend, guardrails=GuardrailConfig())
    assert result.response.choices[0].message.content == "world"
    assert result.response.usage.prompt_tokens > 0
    assert result.response.puffin_metadata["backend"] == "echo"


def test_inference_pipeline_strips_json_fences():
    backend = EchoBackend(rules=[(".*", '```json\n{"a":1}\n```')])
    req = _req(
        [{"role": "user", "content": "x"}],
        response_format={"type": "json_object"},
    )
    result = run_chat_completion(req, backend=backend, guardrails=GuardrailConfig())
    assert result.response.choices[0].message.content == '{"a":1}'


def test_inference_pipeline_request_id_propagates():
    backend = EchoBackend()
    req = _req([{"role": "user", "content": "hi"}])
    result = run_chat_completion(
        req,
        backend=backend,
        guardrails=GuardrailConfig(),
        request_id="custom-rid",
    )
    assert result.request_id == "custom-rid"
    assert result.response.id == "custom-rid"


def test_coerce_request_validates():
    req = coerce_request({"model": "x", "messages": [{"role": "user", "content": "hi"}]})
    assert isinstance(req, ChatCompletionRequest)


def test_inference_pipeline_truncates_at_stop():
    backend = EchoBackend(rules=[(".*", "ABC[END]rest")])
    req = _req([{"role": "user", "content": "x"}], stop=["[END]"])
    result = run_chat_completion(req, backend=backend, guardrails=GuardrailConfig())
    assert result.response.choices[0].message.content == "ABC"
