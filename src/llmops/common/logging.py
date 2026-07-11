"""Structured JSON logging with optional PII redaction."""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

from pythonjsonlogger import jsonlogger

_REDACT_KEYS = {
    "prompt",
    "completion",
    "messages",
    "input",
    "output",
    "content",
    "user_input",
    "assistant_response",
}

_CONFIGURED = False


class RedactingJsonFormatter(jsonlogger.JsonFormatter):
    """JSON formatter that masks known sensitive fields when configured."""

    def __init__(self, *args: Any, redact: bool = False, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.redact = redact

    def add_fields(
        self,
        log_record: dict[str, Any],
        record: logging.LogRecord,
        message_dict: dict[str, Any],
    ) -> None:
        super().add_fields(log_record, record, message_dict)
        log_record.setdefault("level", record.levelname)
        log_record.setdefault("logger", record.name)
        log_record.setdefault("module", record.module)
        if self.redact:
            for key in list(log_record):
                if key in _REDACT_KEYS:
                    log_record[key] = "[REDACTED]"


def configure_logging(
    level: str | None = None,
    fmt: str | None = None,
    redact: bool | None = None,
    force: bool = False,
) -> None:
    """Idempotently configure root logging.

    Reads PUFFIN_LOG_LEVEL, PUFFIN_LOG_FORMAT (json|text), PUFFIN_REDACT_LOGS.
    """
    global _CONFIGURED
    if _CONFIGURED and not force:
        return

    resolved_level = (level or os.environ.get("PUFFIN_LOG_LEVEL", "INFO")).upper()
    resolved_fmt = fmt or os.environ.get("PUFFIN_LOG_FORMAT", "json")
    resolved_redact = (
        redact
        if redact is not None
        else os.environ.get("PUFFIN_REDACT_LOGS", "false").lower() == "true"
    )

    handler = logging.StreamHandler(sys.stdout)
    if resolved_fmt == "json":
        formatter: logging.Formatter = RedactingJsonFormatter(
            "%(asctime)s %(level)s %(logger)s %(message)s",
            redact=resolved_redact,
        )
    else:
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(resolved_level)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Get a configured logger; auto-configures on first call."""
    if not _CONFIGURED:
        configure_logging()
    return logging.getLogger(name)
