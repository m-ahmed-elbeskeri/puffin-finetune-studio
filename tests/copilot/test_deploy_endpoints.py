"""Deploy studio REST: config defaults + the dangerous push/promote gate."""
from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from copilot.backend import deploy_ops
from copilot.backend.app import create_app
from copilot.backend.settings import Settings


def _client(repo: Path, *, dangerous: bool) -> TestClient:
    return TestClient(create_app(settings=Settings(
        anthropic_api_key="", repo_root=repo,
        db_path=repo / "artifacts" / "copilot" / "threads.sqlite3",
        enable_dangerous_tools=dangerous)))


def test_deploy_config_defaults(repo: Path) -> None:
    with _client(repo, dangerous=False) as client:
        body = client.get("/api/deploy/config").json()
        assert body["kind"] == "deploy_config"
        assert body["name"]  # a default name even without configs/deploy.yaml
        assert body["default_alias"]


def test_deploy_config_reads_yaml(repo: Path) -> None:
    (repo / "configs" / "deploy.yaml").write_text(
        "model:\n  name: support-bot\n  alias: production\n", encoding="utf-8")
    with _client(repo, dangerous=False) as client:
        body = client.get("/api/deploy/config").json()
        assert body["name"] == "support-bot"
        assert body["default_alias"] == "production"


def test_push_and_promote_blocked_when_not_dangerous(repo: Path) -> None:
    with _client(repo, dangerous=False) as client:
        push = client.post("/api/deploy/push", json={"name": "m", "alias": "staging"}).json()
        assert push["kind"] == "error" and "disabled" in push["message"].lower()
        prom = client.post("/api/deploy/promote",
                           json={"name": "m", "version": "1", "alias": "production"}).json()
        assert prom["kind"] == "error" and "disabled" in prom["message"].lower()


def test_render_k8s_manifest(repo: Path) -> None:
    # Rendering is not a dangerous action; it just produces YAML.
    with _client(repo, dangerous=False) as client:
        r = client.post("/api/deploy/k8s", json={
            "replicas": 3, "namespace": "puffin", "gpu": True})
        assert r.status_code == 200
        body = r.json()
        assert body["kind"] == "k8s_manifest"
        assert "kind: Deployment" in body["yaml"]
        assert "replicas: 3" in body["yaml"]


def test_deploy_targets_readiness(repo: Path) -> None:
    with _client(repo, dangerous=False) as client:
        body = client.get("/api/deploy/targets").json()
        ids = {t["id"] for t in body["targets"]}
        assert {"kubernetes", "docker", "aws", "gcp", "azure"} <= ids
        for t in body["targets"]:
            assert "cli_installed" in t and "cloud" in t


def test_deploy_build_plan_rejects_shell_injection(repo: Path) -> None:
    # A namespace with shell metacharacters must be refused (it lands in a shell).
    with pytest.raises(deploy_ops.DeployError):
        deploy_ops._build_plan(repo, "kubernetes", {"namespace": "puffin; rm -rf /"})


def test_deploy_run_locked_and_validated(repo: Path) -> None:
    with _client(repo, dangerous=False) as client:
        assert client.post("/api/deploy/run",
                           json={"target": "docker", "settings": {}}).status_code == 403
    with _client(repo, dangerous=True) as client:
        assert client.post("/api/deploy/run",
                           json={"target": "nope", "settings": {}}).status_code == 400
        assert client.post("/api/deploy/run", json={
            "target": "docker", "settings": {"backend": "evil"}}).status_code == 400


def test_deploy_status_and_log_absent(repo: Path) -> None:
    with _client(repo, dangerous=False) as client:
        assert client.get("/api/deploy/status").json()["running"] is False
        assert client.get("/api/deploy/log").json()["present"] is False
