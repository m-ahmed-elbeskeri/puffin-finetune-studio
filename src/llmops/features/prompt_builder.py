"""Shared prompt construction logic.

THE single source of truth for building prompts. Both the training data
pipeline (constructing supervised examples) and the inference pipeline
(constructing live requests) import this. Drift between training and
serving prompts is the #1 cause of fine-tune quality regressions.
"""

from __future__ import annotations

from collections.abc import Sequence

from llmops.features.chat_template import (
    DEFAULT_CHAT_TEMPLATE_VERSION,
    apply_chat_template,
)
from llmops.features.rag_context import RetrievedDocument, format_rag_context
from llmops.features.schemas import Message, Role

PROMPT_BUILDER_VERSION = "1.0.0"


def build_messages(
    user_input: str,
    *,
    system_prompt: str | None = None,
    retrieved_context: Sequence[RetrievedDocument] | None = None,
    chat_history: Sequence[Message] | None = None,
) -> list[Message]:
    """Build the canonical message list for a single turn.

    Order:
        1. System prompt (if any).
        2. RAG context system message (if any docs).
        3. Prior chat history.
        4. New user input.

    Used by:
      - training: to materialize SFT examples from raw fields.
      - serving: to build the input passed to the model.

    Returning a `list[Message]` (not raw strings) lets the chat template
    layer handle role-specific formatting.
    """
    messages: list[Message] = []

    if system_prompt:
        messages.append(Message(role=Role.SYSTEM, content=system_prompt))

    if retrieved_context:
        rag_block = format_rag_context(retrieved_context)
        messages.append(Message(role=Role.SYSTEM, content=rag_block))

    if chat_history:
        messages.extend(chat_history)

    messages.append(Message(role=Role.USER, content=user_input))
    return messages


def build_training_text(
    messages: Sequence[Message],
    *,
    chat_template_version: str = DEFAULT_CHAT_TEMPLATE_VERSION,
    eos_token: str = "</s>",
) -> str:
    """Render a message list into the supervised training string.

    The trailing assistant message must end with `eos_token` so the loss
    boundary is correct. The pure-Python `apply_chat_template` enforces this.
    """
    return apply_chat_template(
        list(messages),
        version=chat_template_version,
        add_generation_prompt=False,
        eos_token=eos_token,
    )
