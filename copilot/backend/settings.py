"""Backend settings — pulled from env, with sensible defaults.

Single source of truth so tests can construct a Settings() with overrides
and never accidentally read os.environ.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _bool(s: str | None, default: bool = False) -> bool:
    if s is None:
        return default
    return s.strip().lower() in {"1", "true", "yes", "on"}


def _path(s: str | None, default: Path) -> Path:
    if not s:
        return default
    return Path(s).expanduser().resolve()


@dataclass(frozen=True)
class Settings:
    """All runtime configuration. Construct once at app startup."""

    # --- Server ---
    host: str = field(
        default_factory=lambda: os.environ.get("PUFFIN_COPILOT_HOST", "127.0.0.1"))
    port: int = field(
        default_factory=lambda: int(os.environ.get("PUFFIN_COPILOT_PORT", "8765")))

    # --- Anthropic ---
    anthropic_api_key: str = field(
        default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY", ""))
    default_model: str = field(
        default_factory=lambda: os.environ.get(
            "PUFFIN_COPILOT_MODEL", "claude-sonnet-4-6"))
    max_tokens: int = field(
        default_factory=lambda: int(
            os.environ.get("PUFFIN_COPILOT_MAX_TOKENS", "8192")))

    # --- Persistence ---
    repo_root: Path = field(
        default_factory=lambda: _path(
            os.environ.get("PUFFIN_REPO_ROOT"),
            Path(__file__).resolve().parents[2],
        ))
    db_path: Path = field(
        default_factory=lambda: _path(
            os.environ.get("PUFFIN_COPILOT_DB"),
            Path(__file__).resolve().parents[2]
            / "artifacts" / "copilot" / "threads.sqlite3",
        ))

    # --- Auth ---
    api_key: str = field(
        default_factory=lambda: os.environ.get("PUFFIN_COPILOT_API_KEY", ""))
    """If set, every request must carry `Authorization: Bearer <api_key>`."""

    # --- CORS ---
    cors_origins: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            x.strip() for x in os.environ.get(
                "PUFFIN_COPILOT_CORS",
                "http://localhost:3000,http://127.0.0.1:3000",
            ).split(",") if x.strip()))

    # --- Behavior ---
    max_tool_iterations: int = field(
        default_factory=lambda: int(
            os.environ.get("PUFFIN_COPILOT_MAX_TOOL_ITERS", "10")))
    """Safety bound on tool-use loop iterations per user turn."""

    enable_dangerous_tools: bool = field(
        default_factory=lambda: _bool(
            os.environ.get("PUFFIN_COPILOT_ENABLE_DANGEROUS"), False))
    """Gate destructive ops (config_edit, train_cancel, deploy_promote)."""

    log_level: str = field(
        default_factory=lambda: os.environ.get(
            "PUFFIN_COPILOT_LOG_LEVEL", "INFO"))

    # --- Frontend static mount (production) ---
    frontend_dist: Path | None = field(
        default_factory=lambda: (
            Path(os.environ["PUFFIN_COPILOT_FRONTEND_DIST"]).expanduser().resolve()
            if os.environ.get("PUFFIN_COPILOT_FRONTEND_DIST") else None
        ))


_settings: Settings | None = None


def get_settings() -> Settings:
    """Singleton accessor. Tests should pass a Settings() directly instead."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings_for_tests() -> None:
    """Drop the singleton so tests can pick up a fresh env."""
    global _settings
    _settings = None
