"""Evaluation studio REST: gate config, gate report, and the dangerous gate."""

from __future__ import annotations

import json
from pathlib import Path

from copilot.backend.app import create_app
from copilot.backend.settings import Settings
from starlette.testclient import TestClient


def _client(repo: Path, *, dangerous: bool) -> TestClient:
    return TestClient(
        create_app(
            settings=Settings(
                anthropic_api_key="",
                repo_root=repo,
                db_path=repo / "artifacts" / "copilot" / "threads.sqlite3",
                enable_dangerous_tools=dangerous,
            )
        )
    )


def test_eval_config_exposes_gate_thresholds(repo: Path) -> None:
    # repo fixture ships configs/eval.yaml with a gates block.
    with _client(repo, dangerous=False) as client:
        r = client.get("/api/eval/config")
        assert r.status_code == 200
        body = r.json()
        assert body["kind"] == "eval_config"
        assert "min_task_score" in body["gates"]


def test_eval_gate_report_absent(repo: Path) -> None:
    with _client(repo, dangerous=False) as client:
        r = client.get("/api/eval/gate")
        assert r.status_code == 200
        assert r.json()["present"] is False


def test_eval_gate_report_read(repo: Path) -> None:
    d = repo / "artifacts" / "eval"
    (d / "gate_report.json").write_text(
        json.dumps({"passed": True, "failures": []}), encoding="utf-8"
    )
    with _client(repo, dangerous=False) as client:
        body = client.get("/api/eval/gate").json()
        assert body["present"] is True
        assert body["passed"] is True


def test_eval_run_blocked_when_not_dangerous(repo: Path) -> None:
    with _client(repo, dangerous=False) as client:
        body = client.post("/api/eval/run", json={"backend": "echo"}).json()
        # The dangerous gate turns the tool into a typed error, not a crash.
        assert body["kind"] == "error"
        assert "disabled" in body["message"].lower()


def test_edit_gate_thresholds_roundtrip(repo: Path) -> None:
    # The fixture's eval.yaml has a comment we assert survives the edit.
    (repo / "configs" / "eval.yaml").write_text(
        "# my gates\ngates:\n  min_task_score: 0.7\n  max_regression_failures: 0\n",
        encoding="utf-8",
    )
    with _client(repo, dangerous=False) as client:
        r = client.put(
            "/api/eval/config",
            json={"gates": {"min_task_score": 0.9, "max_regression_failures": 2}},
        )
        assert r.status_code == 200
        assert r.json()["gates"]["min_task_score"] == 0.9
        # Persisted + comment preserved + counts stay ints.
        text = (repo / "configs" / "eval.yaml").read_text(encoding="utf-8")
        assert "# my gates" in text
        assert "max_regression_failures: 2" in text
        assert client.get("/api/eval/config").json()["gates"]["min_task_score"] == 0.9


def test_edit_gate_rejects_unknown_key(repo: Path) -> None:
    with _client(repo, dangerous=False) as client:
        r = client.put("/api/eval/config", json={"gates": {"rm_rf": 1}})
        assert r.status_code == 400
        assert "unknown gate" in r.json()["detail"]
