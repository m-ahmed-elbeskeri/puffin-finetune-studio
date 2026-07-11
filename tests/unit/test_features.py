"""Tests for the SHARED features module — the anti-skew defense."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from llmops.features.chat_template import (
    DEFAULT_CHAT_TEMPLATE_VERSION,
    apply_chat_template,
    get_chat_template,
)
from llmops.features.prompt_builder import build_messages, build_training_text
from llmops.features.rag_context import RetrievedDocument, format_rag_context
from llmops.features.schemas import (
    ChatCompletionRequest,
    Message,
    PreferenceExample,
    Role,
    SFTExample,
)

# -- schemas --


def test_message_validation_strict():
    with pytest.raises(ValidationError):
        Message.model_validate({"role": "x", "content": "hi"})


def test_message_extra_field_forbidden():
    with pytest.raises(ValidationError):
        Message.model_validate({"role": "user", "content": "hi", "extra": "x"})


def test_sft_example_minimum():
    ex = SFTExample.model_validate(
        {"id": "1", "source": "x", "messages": [{"role": "user", "content": "hi"}]}
    )
    assert ex.quality_score == 1.0


def test_sft_example_quality_bounds():
    with pytest.raises(ValidationError):
        SFTExample.model_validate(
            {
                "id": "1",
                "source": "x",
                "messages": [{"role": "user", "content": "hi"}],
                "quality_score": 1.5,
            }
        )


def test_preference_example_required_fields():
    with pytest.raises(ValidationError):
        PreferenceExample.model_validate({"prompt": "p", "chosen": "c"})


def test_chat_completion_request_temperature_clamp():
    with pytest.raises(ValidationError):
        ChatCompletionRequest.model_validate(
            {
                "model": "x",
                "messages": [{"role": "user", "content": "hi"}],
                "temperature": 5.0,
            }
        )


# -- chat template --


def test_chat_template_known_version():
    assert "user" in get_chat_template(DEFAULT_CHAT_TEMPLATE_VERSION)


def test_chat_template_unknown_raises():
    with pytest.raises(ValueError):
        get_chat_template("v999")


def test_apply_chat_template_renders_roles():
    rendered = apply_chat_template(
        [
            Message(role=Role.SYSTEM, content="sys"),
            Message(role=Role.USER, content="hi"),
            Message(role=Role.ASSISTANT, content="hello"),
        ],
        eos_token="</s>",
    )
    assert "<|system|>" in rendered
    assert "<|user|>" in rendered
    assert "<|assistant|>" in rendered
    assert rendered.endswith("hello</s>")


def test_apply_chat_template_generation_prompt():
    rendered = apply_chat_template(
        [Message(role=Role.USER, content="hi")],
        add_generation_prompt=True,
    )
    assert rendered.endswith("<|assistant|>\n")


def test_apply_chat_template_dict_input():
    rendered = apply_chat_template([{"role": "user", "content": "hi"}])
    assert "hi" in rendered


# -- prompt builder (the load-bearing anti-skew check) --


def test_build_messages_order():
    msgs = build_messages("hello", system_prompt="be helpful")
    assert [m.role for m in msgs] == [Role.SYSTEM, Role.USER]


def test_build_messages_with_rag():
    docs = [RetrievedDocument(id="d1", text="snippet", source="kb")]
    msgs = build_messages("hello", system_prompt="sys", retrieved_context=docs)
    assert len(msgs) == 3
    assert "snippet" in msgs[1].content


def test_anti_skew_training_and_serving_match():
    """Training-time supervised text and serving-time prompt MUST share logic.

    Both go through `build_messages` + `apply_chat_template`. This test fails
    loudly if anyone forks the prompt code.
    """
    user = "How do I reset my password?"
    sys_p = "You are a helpful agent."

    training_msgs = build_messages(user, system_prompt=sys_p)
    training_msgs_with_completion = [
        *training_msgs,
        Message(role=Role.ASSISTANT, content="Click the link."),
    ]
    train_text = build_training_text(training_msgs_with_completion, eos_token="</s>")

    serving_msgs = build_messages(user, system_prompt=sys_p)
    serving_text = apply_chat_template(serving_msgs, add_generation_prompt=True)

    assert serving_msgs == training_msgs
    # Up to the first `<|assistant|>` they must match exactly:
    train_prefix = train_text.split("<|assistant|>")[0]
    serve_prefix = serving_text.split("<|assistant|>")[0]
    assert train_prefix == serve_prefix


# -- RAG context --


def test_format_rag_empty():
    assert "[No documents" in format_rag_context([])


def test_format_rag_renders_docs():
    docs = [
        RetrievedDocument(id="d1", text="alpha", source="kb", score=0.9),
        RetrievedDocument(id="d2", text="beta"),
    ]
    out = format_rag_context(docs)
    assert "[d1]" in out
    assert "alpha" in out
    assert "[d2]" in out
    assert "beta" in out
