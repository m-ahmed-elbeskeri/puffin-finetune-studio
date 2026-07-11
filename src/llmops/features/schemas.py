"""Pydantic schemas for chat messages, training examples, and serving I/O.

Imported by both training (data validation, batch construction) and serving
(request validation, response shaping). Changes here are breaking changes for
the whole pipeline — bump SCHEMA_VERSION when changing.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

SCHEMA_VERSION = "1.0.0"


class Role(str, Enum):  # noqa: UP042 - StrEnum repr changes break formatted prompts
    """Allowed message roles."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class Message(BaseModel):
    """A single chat message."""

    model_config = ConfigDict(extra="forbid")

    role: Role
    content: Annotated[str, StringConstraints(min_length=0, max_length=200_000)]
    name: str | None = None
    tool_call_id: str | None = None


class SFTExample(BaseModel):
    """One supervised fine-tuning example."""

    model_config = ConfigDict(extra="forbid")

    id: str
    source: str
    messages: list[Message] = Field(min_length=1)
    quality_score: float = Field(ge=0.0, le=1.0, default=1.0)
    license: str = "unknown"
    contains_pii: bool = False
    created_at: datetime | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class PreferenceExample(BaseModel):
    """One preference (DPO) training example."""

    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    prompt: str = Field(min_length=1)
    chosen: str = Field(min_length=1)
    rejected: str = Field(min_length=1)
    reason: str | None = None
    labeler_id: str | None = None


class ChatCompletionRequest(BaseModel):
    """OpenAI-compatible chat completion request."""

    model_config = ConfigDict(extra="forbid")

    model: str
    messages: list[Message] = Field(min_length=1)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    top_p: float = Field(default=1.0, ge=0.0, le=1.0)
    max_tokens: int | None = Field(default=None, ge=1, le=32_000)
    stream: bool = False
    user: str | None = None
    stop: list[str] | None = None
    seed: int | None = None
    response_format: dict[str, str] | None = None


class Usage(BaseModel):
    """Token usage stats."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatChoice(BaseModel):
    index: int
    message: Message
    finish_reason: Literal["stop", "length", "content_filter", "tool_calls"]


class ChatCompletionResponse(BaseModel):
    """OpenAI-compatible chat completion response."""

    model_config = ConfigDict(extra="allow")

    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int
    model: str
    choices: list[ChatChoice]
    usage: Usage
    system_fingerprint: str | None = None
    puffin_metadata: dict[str, str] | None = None
