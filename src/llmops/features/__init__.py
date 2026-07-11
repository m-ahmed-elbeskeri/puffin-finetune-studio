"""Shared features used by BOTH training and serving.

This package is the single most important anti-skew defense in the project:
both the training data pipeline and the inference pipeline import from here
to build prompts, format chat messages, tokenize, and validate I/O schemas.

NEVER duplicate logic from this module elsewhere.
"""
from llmops.features.chat_template import (
    CHAT_TEMPLATE_VERSIONS,
    apply_chat_template,
    get_chat_template,
)
from llmops.features.prompt_builder import (
    PROMPT_BUILDER_VERSION,
    build_messages,
    build_training_text,
)
from llmops.features.rag_context import RetrievedDocument, format_rag_context
from llmops.features.schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    Message,
    PreferenceExample,
    Role,
    SFTExample,
)
from llmops.features.tokenization import TokenizerWrapper, load_tokenizer

__all__ = [
    "CHAT_TEMPLATE_VERSIONS",
    "PROMPT_BUILDER_VERSION",
    "ChatCompletionRequest",
    "ChatCompletionResponse",
    "Message",
    "PreferenceExample",
    "RetrievedDocument",
    "Role",
    "SFTExample",
    "TokenizerWrapper",
    "apply_chat_template",
    "build_messages",
    "build_training_text",
    "format_rag_context",
    "get_chat_template",
    "load_tokenizer",
]
