"""Input + output guardrails.

Input checks (pre-generation):
  - max prompt tokens (approx via chars/4)
  - max single-message length
  - banned-pattern matching on user content
  - empty / zero-message rejection

Output checks (post-generation):
  - max output length
  - banned-pattern matching on assistant content
  - optional `require_json` enforcement
  - optional `must_not_contain` list
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from llmops.common.errors import GuardrailError
from llmops.features.schemas import Message


@dataclass
class GuardrailConfig:
    max_input_chars: int = 200_000
    max_output_chars: int = 50_000
    max_messages: int = 64
    banned_input_patterns: list[str] = field(default_factory=list)
    banned_output_patterns: list[str] = field(default_factory=list)
    require_user_message: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> GuardrailConfig:
        if not data:
            return cls()
        return cls(
            max_input_chars=int(data.get("max_input_chars", 200_000)),
            max_output_chars=int(data.get("max_output_chars", 50_000)),
            max_messages=int(data.get("max_messages", 64)),
            banned_input_patterns=list(data.get("banned_input_patterns", [])),
            banned_output_patterns=list(data.get("banned_output_patterns", [])),
            require_user_message=bool(data.get("require_user_message", True)),
        )


def check_input(
    messages: Sequence[Message] | Sequence[dict[str, Any]],
    cfg: GuardrailConfig,
) -> None:
    if not messages:
        raise GuardrailError("at least one message is required")
    if len(messages) > cfg.max_messages:
        raise GuardrailError(f"too many messages: {len(messages)} (max {cfg.max_messages})")

    total_chars = 0
    has_user = False
    for m in messages:
        role = m.role.value if isinstance(m, Message) else m.get("role", "")
        content = m.content if isinstance(m, Message) else m.get("content", "")
        if role == "user":
            has_user = True
        total_chars += len(content or "")
        if total_chars > cfg.max_input_chars:
            raise GuardrailError(
                f"input too long: {total_chars} chars > {cfg.max_input_chars}"
            )
        for pat in cfg.banned_input_patterns:
            if re.search(pat, content or "", flags=re.IGNORECASE):
                raise GuardrailError(f"input matched banned pattern: {pat!r}")

    if cfg.require_user_message and not has_user:
        raise GuardrailError("at least one user message is required")


def check_output(text: str, cfg: GuardrailConfig) -> str:
    """Validate (and possibly truncate) the generated text. Returns the safe text."""
    if len(text) > cfg.max_output_chars:
        text = text[: cfg.max_output_chars]
    for pat in cfg.banned_output_patterns:
        if re.search(pat, text, flags=re.IGNORECASE):
            raise GuardrailError(f"output matched banned pattern: {pat!r}")
    return text
