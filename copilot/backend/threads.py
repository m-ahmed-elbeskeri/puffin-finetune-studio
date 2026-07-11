"""SQLite-backed conversation persistence (async).

Schema (kept deliberately flat):

  threads(id, title, model, created_at, updated_at, deleted)
  messages(id, thread_id, idx, role, content_json, created_at)

`content_json` stores the full Anthropic-shaped content list so we can
replay a conversation losslessly: a single message may contain text +
tool_use + tool_result blocks.
"""
from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite


SCHEMA = """
CREATE TABLE IF NOT EXISTS threads (
  id          TEXT PRIMARY KEY,
  title       TEXT NOT NULL,
  model       TEXT NOT NULL,
  project_id  TEXT,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL,
  deleted     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
  id           TEXT PRIMARY KEY,
  thread_id    TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
  idx          INTEGER NOT NULL,
  role         TEXT NOT NULL,
  content_json TEXT NOT NULL,
  created_at   TEXT NOT NULL,
  UNIQUE(thread_id, idx)
);

CREATE INDEX IF NOT EXISTS idx_messages_thread
  ON messages(thread_id, idx);
CREATE INDEX IF NOT EXISTS idx_threads_updated
  ON threads(updated_at DESC) WHERE deleted = 0;
"""

# Created AFTER the project_id ALTER so it doesn't reference a column
# that doesn't yet exist on an old database.
_INDEX_PROJECT = """
CREATE INDEX IF NOT EXISTS idx_threads_project
  ON threads(project_id, updated_at DESC) WHERE deleted = 0
"""


# In-place migration for databases that pre-date the project_id column.
# Idempotent — only runs the ALTER if the column is missing.
_MIGRATE_PROJECT_ID = """
SELECT COUNT(*) FROM pragma_table_info('threads') WHERE name = 'project_id'
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(12)}"


@dataclass(frozen=True)
class Thread:
    id: str
    title: str
    model: str
    project_id: str | None
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "title": self.title, "model": self.model,
            "project_id": self.project_id,
            "created_at": self.created_at, "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class Message:
    id: str
    thread_id: str
    idx: int
    role: str                       # "user" | "assistant"
    content: list[dict[str, Any]]   # Anthropic-shaped content blocks
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "thread_id": self.thread_id, "idx": self.idx,
            "role": self.role, "content": self.content,
            "created_at": self.created_at,
        }


class ThreadStore:
    """Tiny async repository — one SQLite file, one connection per query."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    async def initialize(self) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(SCHEMA)
            await db.execute("PRAGMA journal_mode=WAL")
            # Migration: pre-existing databases lack project_id. Add the
            # column BEFORE creating the index that references it.
            cur = await db.execute(_MIGRATE_PROJECT_ID)
            (present,) = await cur.fetchone()
            if not present:
                await db.execute("ALTER TABLE threads ADD COLUMN project_id TEXT")
            await db.execute(_INDEX_PROJECT)
            await db.commit()

    # ---- Threads --------------------------------------------------------
    async def create_thread(
        self, *, title: str, model: str, project_id: str | None = None,
    ) -> Thread:
        now = _now()
        tid = _new_id("thr")
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO threads(id, title, model, project_id, "
                "created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?)",
                (tid, title, model, project_id, now, now),
            )
            await db.commit()
        return Thread(id=tid, title=title, model=model, project_id=project_id,
                      created_at=now, updated_at=now)

    async def list_threads(
        self, *, limit: int = 100, project_id: str | None = None,
    ) -> list[Thread]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            if project_id is None:
                cur = await db.execute(
                    "SELECT id, title, model, project_id, created_at, updated_at "
                    "FROM threads WHERE deleted = 0 "
                    "ORDER BY updated_at DESC LIMIT ?",
                    (limit,),
                )
            else:
                # Strict project scoping. NULL project_id rows should have
                # been backfilled at startup (see ThreadStore.backfill_project_id),
                # so we don't surface them as a fallback.
                cur = await db.execute(
                    "SELECT id, title, model, project_id, created_at, updated_at "
                    "FROM threads WHERE deleted = 0 AND project_id = ? "
                    "ORDER BY updated_at DESC LIMIT ?",
                    (project_id, limit),
                )
            rows = await cur.fetchall()
            return [Thread(**dict(r)) for r in rows]

    async def get_thread(self, thread_id: str) -> Thread | None:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT id, title, model, project_id, created_at, updated_at "
                "FROM threads WHERE id = ? AND deleted = 0",
                (thread_id,),
            )
            row = await cur.fetchone()
            return Thread(**dict(row)) if row else None

    async def rename_thread(self, thread_id: str, title: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE threads SET title = ?, updated_at = ? WHERE id = ?",
                (title, _now(), thread_id),
            )
            await db.commit()

    async def set_model(self, thread_id: str, model: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE threads SET model = ?, updated_at = ? WHERE id = ?",
                (model, _now(), thread_id),
            )
            await db.commit()

    async def delete_thread(self, thread_id: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE threads SET deleted = 1, updated_at = ? WHERE id = ?",
                (_now(), thread_id),
            )
            await db.commit()

    async def touch_thread(self, thread_id: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE threads SET updated_at = ? WHERE id = ?",
                (_now(), thread_id),
            )
            await db.commit()

    # ---- Messages -------------------------------------------------------
    async def append_message(
        self,
        thread_id: str,
        *,
        role: str,
        content: list[dict[str, Any]],
    ) -> Message:
        now = _now()
        mid = _new_id("msg")
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT COALESCE(MAX(idx), -1) + 1 FROM messages WHERE thread_id = ?",
                (thread_id,),
            )
            (next_idx,) = await cur.fetchone()
            await db.execute(
                "INSERT INTO messages(id, thread_id, idx, role, content_json, "
                "created_at) VALUES(?, ?, ?, ?, ?, ?)",
                (mid, thread_id, int(next_idx), role,
                 json.dumps(content, default=str), now),
            )
            await db.execute(
                "UPDATE threads SET updated_at = ? WHERE id = ?",
                (now, thread_id),
            )
            await db.commit()
        return Message(id=mid, thread_id=thread_id, idx=int(next_idx),
                       role=role, content=content, created_at=now)

    async def truncate_messages(self, thread_id: str, from_idx: int) -> int:
        """Delete messages with idx >= from_idx. Returns rows deleted.

        Powers regenerate / edit-and-resend: the client rewinds history to
        just before a user message, then streams a fresh reply.
        """
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "DELETE FROM messages WHERE thread_id = ? AND idx >= ?",
                (thread_id, int(from_idx)),
            )
            await db.execute(
                "UPDATE threads SET updated_at = ? WHERE id = ?",
                (_now(), thread_id),
            )
            await db.commit()
            return cur.rowcount or 0

    async def backfill_project_id(self, default_project_id: str) -> int:
        """One-shot migration: assign `default_project_id` to every thread
        that has a NULL project_id. Returns the number of rows updated.
        Idempotent — safe to call on every startup."""
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "UPDATE threads SET project_id = ? WHERE project_id IS NULL",
                (default_project_id,),
            )
            await db.commit()
            return cur.rowcount or 0

    async def list_messages(self, thread_id: str) -> list[Message]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT id, thread_id, idx, role, content_json, created_at "
                "FROM messages WHERE thread_id = ? ORDER BY idx ASC",
                (thread_id,),
            )
            rows = await cur.fetchall()
            out: list[Message] = []
            for r in rows:
                content = json.loads(r["content_json"]) if r["content_json"] else []
                out.append(Message(
                    id=r["id"], thread_id=r["thread_id"], idx=r["idx"],
                    role=r["role"], content=content, created_at=r["created_at"],
                ))
            return out

    async def to_anthropic_messages(self, thread_id: str) -> list[dict[str, Any]]:
        """Project stored messages into the shape Anthropic's API expects."""
        msgs = await self.list_messages(thread_id)
        return [{"role": m.role, "content": m.content} for m in msgs]
