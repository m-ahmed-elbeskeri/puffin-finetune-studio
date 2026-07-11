from __future__ import annotations

import json
import logging

from llmops.common.logging import RedactingJsonFormatter, configure_logging, get_logger


def test_get_logger_smoke():
    log = get_logger("puffin.test")
    log.info("hello")  # should not raise


def test_redacting_formatter_redacts():
    fmt = RedactingJsonFormatter(redact=True)
    record = logging.LogRecord(
        name="x",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="ok",
        args=None,
        exc_info=None,
    )
    record.prompt = "secret"
    out = json.loads(fmt.format(record))
    assert out["prompt"] == "[REDACTED]"


def test_redacting_formatter_passthrough_when_off():
    fmt = RedactingJsonFormatter(redact=False)
    record = logging.LogRecord(
        name="x", level=logging.INFO, pathname=__file__, lineno=1,
        msg="ok", args=None, exc_info=None,
    )
    record.prompt = "secret"
    out = json.loads(fmt.format(record))
    assert out["prompt"] == "secret"


def test_configure_logging_idempotent():
    configure_logging(force=True, fmt="text")
    handlers_before = len(logging.getLogger().handlers)
    configure_logging()  # second call must NOT add handlers
    assert len(logging.getLogger().handlers) == handlers_before
