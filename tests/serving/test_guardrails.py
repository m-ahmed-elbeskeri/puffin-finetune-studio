from __future__ import annotations

import pytest

from llmops.common.errors import GuardrailError
from llmops.features.schemas import Message, Role
from llmops.serving.guardrails import GuardrailConfig, check_input, check_output


def _msg(role: str, content: str) -> Message:
    return Message(role=Role(role), content=content)


def test_empty_messages_rejected():
    with pytest.raises(GuardrailError):
        check_input([], GuardrailConfig())


def test_missing_user_message_rejected():
    with pytest.raises(GuardrailError):
        check_input([_msg("system", "sys")], GuardrailConfig())


def test_too_many_messages_rejected():
    msgs = [_msg("user", "x") for _ in range(70)]
    with pytest.raises(GuardrailError):
        check_input(msgs, GuardrailConfig(max_messages=64))


def test_input_chars_exceeded():
    with pytest.raises(GuardrailError):
        check_input([_msg("user", "x" * 100)], GuardrailConfig(max_input_chars=10))


def test_banned_input_pattern():
    cfg = GuardrailConfig(banned_input_patterns=[r"DROP\s+TABLE"])
    with pytest.raises(GuardrailError):
        check_input([_msg("user", "DROP TABLE users;")], cfg)


def test_check_output_truncates():
    cfg = GuardrailConfig(max_output_chars=5)
    out = check_output("abcdefghij", cfg)
    assert out == "abcde"


def test_check_output_banned_pattern():
    cfg = GuardrailConfig(banned_output_patterns=["secret"])
    with pytest.raises(GuardrailError):
        check_output("here is a secret", cfg)


def test_guardrail_config_from_dict_defaults():
    cfg = GuardrailConfig.from_dict(None)
    assert cfg.max_messages == 64


def test_guardrail_config_from_dict_overrides():
    cfg = GuardrailConfig.from_dict({"max_messages": 8, "banned_input_patterns": ["x"]})
    assert cfg.max_messages == 8
    assert cfg.banned_input_patterns == ["x"]
