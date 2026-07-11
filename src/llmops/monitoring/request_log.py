"""JSON-line request logger with PII-aware controls.

Each request is logged as a single line for easy ingestion by log aggregators.
The `log_inputs` and `log_outputs` flags control whether the actual prompt /
response text is recorded (default: NO — to minimize PII spillage).
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _hash_user(user: str | None) -> str | None:
    if not user:
        return None
    salt = os.environ.get("PUFFIN_USER_HASH_SALT", "puffin-default-salt")
    return hashlib.sha256(f"{salt}::{user}".encode()).hexdigest()[:16]


class RequestLogger:
    """Append-only JSONL logger.

    Thread-safe via a lock around writes.
    """

    def __init__(
        self,
        log_path: str | Path | None = None,
        *,
        log_inputs: bool = False,
        log_outputs: bool = False,
        feedback_path: str | Path | None = None,
    ) -> None:
        self.log_path = Path(log_path) if log_path else None
        self.feedback_path = Path(feedback_path) if feedback_path else (
            self.log_path.with_name("feedback.jsonl") if self.log_path else None
        )
        self.log_inputs = log_inputs
        self.log_outputs = log_outputs
        self._lock = threading.Lock()
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def _write(self, target: Path | None, payload: dict[str, Any]) -> None:
        if target is None:
            return
        line = json.dumps(payload, ensure_ascii=False, default=str)
        with self._lock, target.open("a", encoding="utf-8") as f:
            f.write(line)
            f.write("\n")

    def log_request(
        self,
        *,
        request_id: str,
        model: str,
        model_version: str,
        backend: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: float,
        user: str | None = None,
        input_messages: list[dict[str, Any]] | None = None,
        output_text: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "request_id": request_id,
            "user_hash": _hash_user(user),
            "model": model,
            "model_version": model_version,
            "backend": backend,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "latency_ms": round(latency_ms, 2),
        }
        if self.log_inputs and input_messages is not None:
            payload["input_messages"] = input_messages
        else:
            payload["input_message_count"] = len(input_messages) if input_messages else 0
        if self.log_outputs and output_text is not None:
            payload["output_text"] = output_text
        else:
            payload["output_chars"] = len(output_text) if output_text else 0
        if extra:
            payload.update(extra)
        self._write(self.log_path, payload)

    def log_error(
        self,
        *,
        request_id: str,
        error_type: str,
        error_message: str,
    ) -> None:
        self._write(
            self.log_path,
            {
                "ts": datetime.now(UTC).isoformat(),
                "request_id": request_id,
                "kind": "error",
                "error_type": error_type,
                "error_message": error_message,
            },
        )

    def log_feedback(
        self,
        *,
        request_id: str,
        score: int | float | None,
        comment: str | None = None,
    ) -> None:
        self._write(
            self.feedback_path,
            {
                "ts": datetime.now(UTC).isoformat(),
                "request_id": request_id,
                "score": score,
                "comment": comment,
            },
        )
