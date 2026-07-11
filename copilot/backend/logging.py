"""Structured JSON logging for the copilot backend.

Same format the rest of llmops uses (one JSON object per line), so logs
ship to the same aggregator without translation.
"""
from __future__ import annotations

import logging
import sys

try:
    from pythonjsonlogger.jsonlogger import JsonFormatter
except ImportError:  # pragma: no cover
    JsonFormatter = None  # type: ignore[assignment]


def setup_logging(level: str = "INFO") -> None:
    """Configure the root logger. Idempotent — safe to call multiple times."""
    root = logging.getLogger()
    if getattr(root, "_puffin_copilot_configured", False):
        return

    handler = logging.StreamHandler(sys.stderr)
    if JsonFormatter is not None:
        handler.setFormatter(JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
            rename_fields={"asctime": "ts", "levelname": "level", "name": "logger"},
        ))
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.handlers = [handler]
    root.setLevel(level.upper())
    root._puffin_copilot_configured = True  # type: ignore[attr-defined]


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
