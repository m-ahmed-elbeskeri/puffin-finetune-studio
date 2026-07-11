"""Tail a file as it grows, yielding new lines via async generator.

Designed to back the `/api/logs/tail` SSE endpoint so the frontend can
follow long-running subprocess output (training logs, data-pipeline
stdout, eval runs) without polling whole-file reads.

Implementation:
- Open the file in text mode at the requested start position.
- On each tick (poll_interval), read whatever's new since last seen.
- Yield individual lines; buffer partial trailing lines until the next
  newline arrives so we never emit half-lines.
- Stop after `max_idle_s` of no growth and no client activity — the
  caller can decide whether to reopen.

Security: callers validate the path against the project's allow-list
BEFORE invoking this — we trust the path here.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import AsyncIterator


DEFAULT_POLL_INTERVAL = 0.5
DEFAULT_MAX_IDLE = 600.0  # ten minutes of silence ends the stream


async def tail_file(
    path: Path,
    *,
    start: int = 0,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    max_idle_s: float = DEFAULT_MAX_IDLE,
) -> AsyncIterator[dict[str, object]]:
    """Yield events as the file grows. Each event is one of:

      {"type": "line",   "text": "..."}     — a complete line (no trailing \\n)
      {"type": "truncated"}                 — file shrunk; we re-seeked to 0
      {"type": "ping"}                      — keep-alive when no growth
      {"type": "eof"}                       — stopped (idle timeout reached)

    The caller is responsible for closing the underlying SSE connection
    when the generator returns.
    """
    p = Path(path)
    pos = max(0, int(start))
    buf = ""
    idle_for = 0.0

    while True:
        try:
            stat = p.stat()
        except FileNotFoundError:
            # The file doesn't exist yet — wait for the producer to make it.
            yield {"type": "ping", "pos": pos}
            await asyncio.sleep(poll_interval)
            idle_for += poll_interval
            if idle_for >= max_idle_s:
                yield {"type": "eof", "reason": "idle"}
                return
            continue

        size = stat.st_size
        if size < pos:
            # File was truncated (or replaced). Reset and re-tail from 0.
            yield {"type": "truncated"}
            pos = 0
            buf = ""

        if size > pos:
            try:
                with p.open("r", encoding="utf-8", errors="replace") as fh:
                    fh.seek(pos)
                    chunk = fh.read()
                    pos = fh.tell()
            except OSError as exc:
                yield {"type": "error", "message": f"read failed: {exc}"}
                await asyncio.sleep(poll_interval)
                continue

            buf += chunk
            # Drain complete lines; keep any trailing partial line in buf.
            *complete, tail = buf.split("\n")
            for line in complete:
                yield {"type": "line", "text": line}
            buf = tail
            idle_for = 0.0
        else:
            yield {"type": "ping", "pos": pos}
            idle_for += poll_interval

        if idle_for >= max_idle_s:
            # Flush any trailing buffer as a final partial line.
            if buf:
                yield {"type": "line", "text": buf}
                buf = ""
            yield {"type": "eof", "reason": "idle"}
            return

        await asyncio.sleep(poll_interval)


def resolve_safe_path(
    *,
    requested: str,
    repo_root: Path,
    allow_dirs: tuple[str, ...] = ("artifacts", "logs"),
) -> Path:
    """Resolve `requested` under `repo_root` and refuse anything outside
    the allow-listed top-level directories. Raises ValueError if the
    requested path tries to escape (../) or points outside.
    """
    repo = Path(repo_root).resolve()
    # Treat the requested string as project-relative if it's not absolute.
    raw = Path(requested)
    candidate = (repo / raw if not raw.is_absolute() else raw).resolve()
    try:
        rel = candidate.relative_to(repo)
    except ValueError as exc:
        raise ValueError(
            f"path is outside the project root: {requested}"
        ) from exc
    top = rel.parts[0] if rel.parts else ""
    if top not in allow_dirs:
        raise ValueError(
            f"path must be inside one of {allow_dirs}; got top={top!r}"
        )
    return candidate
