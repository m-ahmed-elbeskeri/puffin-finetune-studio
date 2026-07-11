"""FastAPI app tests using TestClient."""

from __future__ import annotations


def _client(monkeypatch, repo_root, tmp_path):
    """Build a TestClient against the echo-backed serving app."""
    monkeypatch.setenv("PUFFIN_DEPLOY_CONFIG", str(repo_root / "configs" / "deploy.yaml"))
    monkeypatch.setenv("PUFFIN_SERVE_BACKEND", "echo")
    monkeypatch.chdir(tmp_path)

    from fastapi.testclient import TestClient

    from llmops.serving.app import create_app

    app = create_app(str(repo_root / "configs" / "deploy.yaml"))
    return TestClient(app)


def test_health(monkeypatch, repo_root, tmp_path):
    with _client(monkeypatch, repo_root, tmp_path) as client:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


def test_ready_after_lifespan(monkeypatch, repo_root, tmp_path):
    with _client(monkeypatch, repo_root, tmp_path) as client:
        r = client.get("/ready")
        assert r.status_code == 200
        assert r.json()["status"] == "ready"


def test_model_version_endpoint(monkeypatch, repo_root, tmp_path):
    with _client(monkeypatch, repo_root, tmp_path) as client:
        r = client.get("/model/version")
        assert r.status_code == 200
        assert "backend" in r.json()


def test_metrics_endpoint(monkeypatch, repo_root, tmp_path):
    with _client(monkeypatch, repo_root, tmp_path) as client:
        client.post(
            "/v1/chat/completions",
            json={
                "model": "test",
                "messages": [{"role": "user", "content": "password reset?"}],
            },
        )
        r = client.get("/metrics")
        assert r.status_code == 200
        # Body may be empty if prometheus_client isn't installed; just verify
        # the endpoint serves content.
        assert isinstance(r.text, str)


def test_chat_completions_happy_path(monkeypatch, repo_root, tmp_path):
    with _client(monkeypatch, repo_root, tmp_path) as client:
        r = client.post(
            "/v1/chat/completions",
            json={
                "model": "test",
                "messages": [{"role": "user", "content": "password reset"}],
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["object"] == "chat.completion"
        assert body["choices"][0]["message"]["role"] == "assistant"
        assert body["puffin_metadata"]["backend"] == "echo"
        assert "request_id" in body["puffin_metadata"]


def test_chat_completions_validation_error(monkeypatch, repo_root, tmp_path):
    with _client(monkeypatch, repo_root, tmp_path) as client:
        r = client.post(
            "/v1/chat/completions",
            json={"model": "test"},  # missing messages
        )
        assert r.status_code == 422


def test_chat_completions_guardrail_blocks_empty_messages(monkeypatch, repo_root, tmp_path):
    with _client(monkeypatch, repo_root, tmp_path) as client:
        r = client.post(
            "/v1/chat/completions",
            json={"model": "test", "messages": []},
        )
        # Either pydantic 422 (min_length=1) or guardrail 400 — both acceptable.
        assert r.status_code in (400, 422)


def test_feedback_endpoint(monkeypatch, repo_root, tmp_path):
    with _client(monkeypatch, repo_root, tmp_path) as client:
        r = client.post(
            "/v1/feedback",
            json={"request_id": "abc", "score": 1, "comment": "great"},
        )
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


def test_feedback_requires_request_id(monkeypatch, repo_root, tmp_path):
    with _client(monkeypatch, repo_root, tmp_path) as client:
        r = client.post("/v1/feedback", json={"score": 1})
        assert r.status_code == 400
