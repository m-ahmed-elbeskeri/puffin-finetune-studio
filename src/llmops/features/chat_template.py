"""Versioned chat templates.

Pinning the chat template version is critical: training applies the template
to build supervised text, and serving applies the same template to build the
input. A version mismatch silently breaks fine-tuning quality.
"""
from __future__ import annotations

from llmops.features.schemas import Message, Role

CHAT_TEMPLATE_VERSIONS = ["v1"]
DEFAULT_CHAT_TEMPLATE_VERSION = "v1"


_V1_TEMPLATE = """{%- for message in messages -%}
{%- if message['role'] == 'system' -%}
<|system|>
{{ message['content'] }}
{%- elif message['role'] == 'user' -%}
<|user|>
{{ message['content'] }}
{%- elif message['role'] == 'assistant' -%}
<|assistant|>
{{ message['content'] }}{{ eos_token }}
{%- endif -%}
{%- endfor -%}
{%- if add_generation_prompt -%}
<|assistant|>
{%- endif -%}
"""


def get_chat_template(version: str = DEFAULT_CHAT_TEMPLATE_VERSION) -> str:
    """Return the Jinja chat template string for a given version.

    The string is intended to be assigned to `tokenizer.chat_template` so the
    same Hugging Face `apply_chat_template` call works consistently in
    training and serving.
    """
    if version == "v1":
        return _V1_TEMPLATE
    raise ValueError(f"Unknown chat template version: {version!r}")


def apply_chat_template(
    messages: list[Message] | list[dict[str, str]],
    *,
    version: str = DEFAULT_CHAT_TEMPLATE_VERSION,
    add_generation_prompt: bool = False,
    eos_token: str = "</s>",
) -> str:
    """Render messages to a single training/inference string.

    This is a pure-Python implementation that does not require a tokenizer to
    be loaded — useful for tests, dataset preview, and lightweight inference
    paths. For real training, prefer `tokenizer.apply_chat_template` after
    setting `tokenizer.chat_template = get_chat_template(version)`.
    """
    if version != "v1":
        raise ValueError(f"Unknown chat template version: {version!r}")

    parts: list[str] = []
    for raw in messages:
        if isinstance(raw, Message):
            role = raw.role.value
            content = raw.content
        else:
            role = raw["role"]
            content = raw["content"]

        if role == Role.SYSTEM.value:
            parts.append(f"<|system|>\n{content}")
        elif role == Role.USER.value:
            parts.append(f"<|user|>\n{content}")
        elif role == Role.ASSISTANT.value:
            parts.append(f"<|assistant|>\n{content}{eos_token}")
        elif role == Role.TOOL.value:
            parts.append(f"<|tool|>\n{content}")
        else:
            raise ValueError(f"Unknown role: {role!r}")

    rendered = "".join(parts)
    if add_generation_prompt:
        rendered += "<|assistant|>\n"
    return rendered
