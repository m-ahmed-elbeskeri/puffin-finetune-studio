"""Server-Sent Events envelope.

Single source of truth for how the backend encodes events on the wire.
Tests use `parse_sse` to round-trip; the frontend's `streaming.ts` mirrors
the same encoding.
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterable, AsyncIterator


def encode_sse(event: str, data: Any) -> bytes:
    """Encode one SSE message. UTF-8. Newlines inside `data` are escaped."""
    payload = json.dumps(data, default=str, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")


async def to_sse(stream: AsyncIterable[dict[str, Any]]) -> AsyncIterator[bytes]:
    """Adapt a loop event stream (event/data dicts) into SSE bytes."""
    async for evt in stream:
        yield encode_sse(evt.get("event", "message"), evt.get("data", {}))


def parse_sse(blob: bytes | str) -> list[tuple[str, Any]]:
    """Parse a chunk of SSE bytes into [(event, data), ...]. Used by tests."""
    if isinstance(blob, bytes):
        blob = blob.decode("utf-8")
    out: list[tuple[str, Any]] = []
    for chunk in blob.split("\n\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        evt = "message"
        data = ""
        for line in chunk.splitlines():
            if line.startswith("event:"):
                evt = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data += line[len("data:"):].strip()
        try:
            parsed = json.loads(data) if data else None
        except json.JSONDecodeError:
            parsed = data
        out.append((evt, parsed))
    return out
