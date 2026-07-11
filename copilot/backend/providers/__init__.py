"""Provider abstraction + factory.

Concrete providers, picked at runtime from the thread's model string:

  anthropic:claude-sonnet-4-6   → AnthropicProvider (direct Messages API)
  claude-code:default           → ClaudeCodeProvider (local CLI via SDK,
                                  with Puffin tools mounted as MCP)
  codex-cli:default             → CodexCliProvider (local `codex exec --json`)
  openai:gpt-5-codex            → OpenAICodexProvider (Codex via OpenAI)
  openai:gpt-5                  → OpenAICodexProvider (same code, diff model)
  gemini-cli:default            → AgentCliProvider (generic adapter; also
  qwen-code / opencode /          covers every other local agent CLI in
  cursor-agent / copilot-cli      AGENT_CLI_CATALOG)
"""
from copilot.backend.providers.base import (
    AssistantEvent,
    AssistantTurn,
    Provider,
    StreamEvent,
)
from copilot.backend.providers.agent_cli import (
    AGENT_CLI_CATALOG,
    AGENT_CLI_SPECS,
    AgentCliProvider,
    AgentCliSpec,
    probe_cli_version,
)
from copilot.backend.providers.anthropic import AnthropicProvider
from copilot.backend.providers.claude_code import ClaudeCodeProvider
from copilot.backend.providers.codex_cli import CodexCliProvider
from copilot.backend.providers.openai_codex import OpenAICodexProvider
from copilot.backend.providers.factory import (
    ProviderHandle, choose_provider, parse_model_id, AVAILABLE_MODELS,
)

__all__ = [
    "AGENT_CLI_CATALOG", "AGENT_CLI_SPECS",
    "AgentCliProvider", "AgentCliSpec", "probe_cli_version",
    "AnthropicProvider", "ClaudeCodeProvider", "CodexCliProvider",
    "OpenAICodexProvider",
    "AssistantEvent", "AssistantTurn", "Provider", "StreamEvent",
    "ProviderHandle", "choose_provider", "parse_model_id", "AVAILABLE_MODELS",
]
