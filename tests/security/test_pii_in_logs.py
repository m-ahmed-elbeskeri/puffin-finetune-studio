"""Verify the request logger does NOT write prompts/outputs by default."""

from __future__ import annotations

import json

from llmops.monitoring.request_log import RequestLogger


def test_request_log_excludes_prompts_by_default(tmp_path):
    log_path = tmp_path / "requests.jsonl"
    rl = RequestLogger(log_path=log_path)
    rl.log_request(
        request_id="r1",
        model="m",
        model_version="v1",
        backend="echo",
        input_tokens=10,
        output_tokens=20,
        latency_ms=100,
        user="alice@example.com",
        input_messages=[{"role": "user", "content": "secret prompt"}],
        output_text="secret reply",
    )
    payload = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert "secret prompt" not in json.dumps(payload)
    assert "secret reply" not in json.dumps(payload)
    assert payload["user_hash"] is not None
    assert payload["input_message_count"] == 1
    assert payload["output_chars"] == len("secret reply")


def test_request_log_includes_when_explicit(tmp_path):
    log_path = tmp_path / "requests.jsonl"
    rl = RequestLogger(log_path=log_path, log_inputs=True, log_outputs=True)
    rl.log_request(
        request_id="r1",
        model="m",
        model_version="v1",
        backend="echo",
        input_tokens=1,
        output_tokens=1,
        latency_ms=1,
        input_messages=[{"role": "user", "content": "ok"}],
        output_text="response",
    )
    payload = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert payload["input_messages"][0]["content"] == "ok"
    assert payload["output_text"] == "response"


def test_user_hash_is_stable(tmp_path, monkeypatch):
    monkeypatch.setenv("PUFFIN_USER_HASH_SALT", "fixed")
    rl1 = RequestLogger(log_path=tmp_path / "a.jsonl")
    rl2 = RequestLogger(log_path=tmp_path / "b.jsonl")
    rl1.log_request(
        request_id="r1",
        model="m",
        model_version="v1",
        backend="b",
        input_tokens=1,
        output_tokens=1,
        latency_ms=1,
        user="alice",
    )
    rl2.log_request(
        request_id="r2",
        model="m",
        model_version="v1",
        backend="b",
        input_tokens=1,
        output_tokens=1,
        latency_ms=1,
        user="alice",
    )
    a_hash = json.loads((tmp_path / "a.jsonl").read_text())["user_hash"]
    b_hash = json.loads((tmp_path / "b.jsonl").read_text())["user_hash"]
    assert a_hash == b_hash
