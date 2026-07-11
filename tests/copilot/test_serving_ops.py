"""UI serving control: status read, idle stop, and the dangerous gate."""
from __future__ import annotations

import json
from pathlib import Path

from starlette.testclient import TestClient

from copilot.backend import serving_ops
from copilot.backend.app import create_app
from copilot.backend.settings import Settings


def _client(repo: Path, *, dangerous: bool) -> TestClient:
    return TestClient(create_app(settings=Settings(
        anthropic_api_key="", repo_root=repo,
        db_path=repo / "artifacts" / "copilot" / "threads.sqlite3",
        enable_dangerous_tools=dangerous)))


def test_status_absent(repo: Path) -> None:
    st = serving_ops.read_state(repo)
    assert st["running"] is False
    assert st["port"] == serving_ops.DEFAULT_PORT


def test_status_dead_pid_is_not_running(repo: Path) -> None:
    p = serving_ops._state_path(repo)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"pid": 999999, "port": 8089}), encoding="utf-8")
    assert serving_ops.read_state(repo)["running"] is False


def test_stop_when_idle(repo: Path) -> None:
    out = serving_ops.stop(repo)
    assert out["stopped"] is False


def test_status_endpoint(repo: Path) -> None:
    with _client(repo, dangerous=False) as client:
        r = client.get("/api/serving/status")
        assert r.status_code == 200
        assert r.json()["running"] is False


def test_start_stop_locked_when_not_dangerous(repo: Path) -> None:
    with _client(repo, dangerous=False) as client:
        assert client.post("/api/serving/start", json={"backend": "echo"}).status_code == 403
        assert client.post("/api/serving/stop").status_code == 403


def test_serving_log_absent(repo: Path) -> None:
    out = serving_ops.read_log(repo)
    assert out["present"] is False


def test_serving_log_reads_newest(repo: Path) -> None:
    logs = repo / "artifacts" / "copilot" / "serving-logs"
    logs.mkdir(parents=True)
    (logs / "serving_20260705T000000.log").write_text("boot\nmodel loaded\n", encoding="utf-8")
    out = serving_ops.read_log(repo, tail=10)
    assert out["present"] is True
    assert out["lines"][-1] == "model loaded"


def test_serve_chat_proxy_errors_gracefully_when_down(repo: Path) -> None:
    # Nothing is serving on the unused port -> a typed error, not a 500.
    with _client(repo, dangerous=False) as client:
        r = client.post("/api/serving/chat", json={
            "prompt": "hi", "url": "http://127.0.0.1:8099"})
        assert r.status_code == 200
        assert r.json()["kind"] == "error"
