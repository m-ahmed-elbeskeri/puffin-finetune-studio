"""Provider factory — turn a `vendor:model` string into a live Provider.

Catalog of vendors:
  anthropic    — direct Anthropic Messages API. Default model claude-sonnet-4-6.
  claude-code  — local Claude Code CLI (via claude-agent-sdk). Default "default"
                 means "whatever the CLI picks". User can override with
                 `claude-code:claude-opus-4-7`.
  openai       — OpenAI chat completions. Default gpt-5-codex; gpt-5 also OK.
  codex        — alias for openai with the Codex default model.
  codex-cli    — local Codex CLI (`codex exec --json`).
  gemini-cli / qwen-code / opencode / cursor-agent / copilot-cli
               — local agent CLIs via the generic AgentCliProvider; entries
                 come from AGENT_CLI_CATALOG so the picker never drifts
                 from what's actually wired.

Front-end gets `AVAILABLE_MODELS` so the picker shows what's actually wired.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from copilot.backend.providers.agent_cli import AGENT_CLI_CATALOG
from copilot.backend.providers.base import Provider


# Default model string a brand-new thread should get if the user picks "auto".
DEFAULT_MODEL = "anthropic:claude-sonnet-4-6"


# Surface-area shown in the frontend picker. `requires` is informational so the
# UI can grey out models whose env var / CLI isn't configured.
AVAILABLE_MODELS: list[dict[str, Any]] = [
    {
        "id": "anthropic:claude-opus-4-7",
        "label": "Claude Opus 4.7",
        "vendor": "anthropic",
        "requires": "ANTHROPIC_API_KEY",
        "description":
            "Anthropic Messages API. Highest reasoning quality. Slowest.",
    },
    {
        "id": "anthropic:claude-sonnet-4-6",
        "label": "Claude Sonnet 4.6",
        "vendor": "anthropic",
        "requires": "ANTHROPIC_API_KEY",
        "description":
            "Anthropic Messages API. Default — fast, solid tool-use.",
    },
    {
        "id": "anthropic:claude-haiku-4-5-20251001",
        "label": "Claude Haiku 4.5",
        "vendor": "anthropic",
        "requires": "ANTHROPIC_API_KEY",
        "description": "Anthropic Messages API. Cheapest / fastest.",
    },
    {
        "id": "claude-code:default",
        "label": "Claude Code (local CLI)",
        "vendor": "claude-code",
        "requires": "claude CLI on PATH",
        "description":
            "Uses your local Claude Code install. Adds Bash/Read/Edit/Glob/Grep "
            "to the 24 Puffin tools — no Anthropic API key needed if your CLI "
            "is already authed.",
    },
    {
        "id": "codex-cli:default",
        "label": "Codex (local CLI)",
        "vendor": "codex-cli",
        "requires": "codex CLI on PATH",
        "description":
            "Spawns `codex exec --json` and streams its JSONL events. Uses your "
            "~/.codex/config.toml for auth + model. Codex's own Bash/Read/Edit "
            "are available; Puffin tools are NOT auto-mounted (register them via "
            "`codex mcp add` if you want both).",
    },
    {
        "id": "openai:gpt-5-codex",
        "label": "GPT-5 Codex",
        "vendor": "openai",
        "requires": "OPENAI_API_KEY",
        "description":
            "OpenAI Codex-class model. Strong agentic tool use.",
    },
    {
        "id": "openai:gpt-5",
        "label": "GPT-5",
        "vendor": "openai",
        "requires": "OPENAI_API_KEY",
        "description":
            "OpenAI flagship via chat completions. Function-calling.",
    },
    # Generic agent CLIs (Gemini, Qwen, OpenCode, Cursor, Copilot) — one
    # entry per catalog spec, wired only when the binary is on PATH.
    *(
        {
            "id": f"{spec.vendor}:default",
            "label": spec.label,
            "vendor": spec.vendor,
            "requires": f"{spec.binary} CLI on PATH",
            "description": spec.description,
        }
        for spec in AGENT_CLI_CATALOG
    ),
]


@dataclass
class ProviderHandle:
    """What the app wires up at startup for each vendor it can serve.

    Held on `app.state.provider_handles` (dict by vendor name). The chat
    endpoint dispatches per thread using `choose_provider`.
    """
    vendor: str
    provider: Provider
    default_model: str


def parse_model_id(model_id: str | None) -> tuple[str, str]:
    """Split `vendor:model` → (vendor, model). Bare strings default to anthropic."""
    if not model_id:
        return "anthropic", "claude-sonnet-4-6"
    if ":" not in model_id:
        return "anthropic", model_id
    vendor, _, model = model_id.partition(":")
    return vendor.strip().lower() or "anthropic", model.strip() or "default"


def choose_provider(
    model_id: str | None,
    handles: dict[str, ProviderHandle],
) -> tuple[ProviderHandle, str]:
    """Pick the provider for this thread's model string. Falls back to the
    first available handle if the requested vendor isn't wired.

    Returns (handle, resolved_model_string) where the model string is the
    bare form (no `vendor:` prefix) the provider expects.
    """
    vendor, model = parse_model_id(model_id)
    if vendor == "codex":
        vendor = "openai"
    handle = handles.get(vendor)
    if handle is None:
        # Use the first wired handle as a fallback.
        if not handles:
            raise RuntimeError(
                "No providers configured. Set ANTHROPIC_API_KEY, "
                "OPENAI_API_KEY, or install the claude CLI."
            )
        handle = next(iter(handles.values()))
    if not model or model == "default":
        model = handle.default_model
    return handle, model
