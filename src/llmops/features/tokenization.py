"""Tokenizer wrapper — identical settings in training and serving."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from llmops.features.chat_template import (
    DEFAULT_CHAT_TEMPLATE_VERSION,
    get_chat_template,
)

if TYPE_CHECKING:
    pass


@dataclass
class TokenizerWrapper:
    """Lightweight wrapper that pins chat template, padding, and special tokens.

    Construct via `load_tokenizer(...)` — that ensures the chat template
    version is recorded and applied consistently.
    """

    tokenizer: Any  # PreTrainedTokenizerBase, untyped to avoid hard import
    chat_template_version: str
    base_model: str
    revision: str

    def encode_chat(
        self,
        messages: list[dict[str, str]],
        *,
        add_generation_prompt: bool = False,
        max_length: int | None = None,
    ) -> dict[str, Any]:
        """Apply chat template and tokenize."""
        text = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=add_generation_prompt,
        )
        kwargs: dict[str, Any] = {"return_tensors": "pt", "truncation": True}
        if max_length is not None:
            kwargs["max_length"] = max_length
        return self.tokenizer(text, **kwargs)


def load_tokenizer(
    base_model: str,
    *,
    revision: str = "main",
    chat_template_version: str = DEFAULT_CHAT_TEMPLATE_VERSION,
    trust_remote_code: bool = False,
) -> TokenizerWrapper:
    """Load a HF tokenizer and pin the chat template.

    Imports `transformers` lazily so this module can be used in lightweight
    contexts (eval, serving with a different backend) without the heavy
    dependency.
    """
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(
        base_model,
        revision=revision,
        use_fast=True,
        trust_remote_code=trust_remote_code,
    )
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    tok.chat_template = get_chat_template(chat_template_version)

    return TokenizerWrapper(
        tokenizer=tok,
        chat_template_version=chat_template_version,
        base_model=base_model,
        revision=revision,
    )
