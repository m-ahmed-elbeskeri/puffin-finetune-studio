"""Project brief: persistence, summary, and REST."""
from __future__ import annotations

from pathlib import Path

from starlette.testclient import TestClient

from copilot.backend import brief_ops
from copilot.backend.app import create_app
from copilot.backend.settings import Settings


def _client(repo: Path) -> TestClient:
    return TestClient(create_app(settings=Settings(
        anthropic_api_key="", repo_root=repo,
        db_path=repo / "artifacts" / "copilot" / "threads.sqlite3",
        enable_dangerous_tools=False)))


def test_brief_absent(repo: Path) -> None:
    b = brief_ops.read_brief(repo)
    assert b["present"] is False
    assert set(b["fields"]) == set(brief_ops.BRIEF_FIELDS)
    assert brief_ops.brief_summary(repo) == ""


def test_brief_write_read_summary(repo: Path) -> None:
    brief_ops.write_brief(repo, {"goal": "A support bot", "audience": "customers"})
    b = brief_ops.read_brief(repo)
    assert b["present"] is True
    assert b["fields"]["goal"] == "A support bot"
    text = (repo / "configs" / "project_brief.yaml").read_text(encoding="utf-8")
    assert "goal:" in text
    summary = brief_ops.brief_summary(repo)
    assert "A support bot" in summary and "customers" in summary


def test_brief_endpoints(repo: Path) -> None:
    with _client(repo) as client:
        client.put("/api/brief", json={"fields": {"goal": "Ship faster"}})
        b = client.get("/api/brief").json()
        assert b["kind"] == "project_brief"
        assert b["fields"]["goal"] == "Ship faster"
        assert b["present"] is True
