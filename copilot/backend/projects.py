"""ProjectStore — SQLite-backed registry of workspaces the copilot can address.

A "project" is just a name + an absolute path on disk. Every tool call goes
through a `ToolContext(repo_root=<that path>, ...)`. The copilot starts with
exactly one project (auto-seeded from the cwd settings.repo_root); the user
adds more via POST /api/projects.

Schema (added to the same threads.sqlite3 DB):

  projects(id, name, path, created_at, deleted)
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite


SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  path        TEXT NOT NULL,
  created_at  TEXT NOT NULL,
  deleted     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_projects_created
  ON projects(created_at DESC) WHERE deleted = 0;
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _new_id() -> str:
    return f"prj_{secrets.token_hex(10)}"


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    path: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "path": self.path,
                "created_at": self.created_at}


class ProjectStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    async def initialize(self, *, default_path: Path) -> Project:
        """Create the table if missing; seed the default project from cwd
        when the table is empty so the copilot has at least one project."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(SCHEMA)
            await db.commit()
        existing = await self.list_projects()
        if existing:
            return existing[0]
        return await self.create_project(
            name=Path(default_path).name or "puffin",
            path=str(default_path),
        )

    async def create_project(self, *, name: str, path: str) -> Project:
        resolved = str(Path(path).expanduser().resolve())
        if not Path(resolved).exists():
            raise ValueError(f"path does not exist: {resolved}")
        pid = _new_id()
        now = _now()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO projects(id, name, path, created_at) "
                "VALUES(?, ?, ?, ?)",
                (pid, name.strip() or "untitled", resolved, now),
            )
            await db.commit()
        return Project(id=pid, name=name, path=resolved, created_at=now)

    async def list_projects(self) -> list[Project]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT id, name, path, created_at FROM projects "
                "WHERE deleted = 0 ORDER BY created_at ASC")
            rows = await cur.fetchall()
            return [Project(**dict(r)) for r in rows]

    async def get_project(self, pid: str) -> Project | None:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT id, name, path, created_at FROM projects "
                "WHERE id = ? AND deleted = 0", (pid,))
            row = await cur.fetchone()
            return Project(**dict(row)) if row else None

    async def delete_project(self, pid: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE projects SET deleted = 1 WHERE id = ?", (pid,))
            await db.commit()
