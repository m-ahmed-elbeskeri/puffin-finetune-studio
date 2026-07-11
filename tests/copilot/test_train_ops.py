"""Training log tail, pre-launch preflight, and resource estimate."""

from __future__ import annotations

import json
from pathlib import Path

from copilot.backend import train_ops
from copilot.backend.app import create_app
from copilot.backend.settings import Settings
from copilot.backend.tools.train import read_run_config, read_training_log
from starlette.testclient import TestClient


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _client(repo: Path) -> TestClient:
    return TestClient(
        create_app(
            settings=Settings(
                anthropic_api_key="",
                repo_root=repo,
                db_path=repo / "artifacts" / "copilot" / "threads.sqlite3",
                enable_dangerous_tools=False,
            )
        )
    )


# ---- log tail -------------------------------------------------------------
def test_read_training_log_via_pointer(repo: Path) -> None:
    d = repo / "artifacts" / "adapter-smoke"
    d.mkdir(parents=True)
    logs = repo / "artifacts" / "copilot" / "training-logs"
    logs.mkdir(parents=True)
    log = logs / "sft_20260704.log"
    log.write_text("\n".join(f"line {i}" for i in range(500)), encoding="utf-8")
    (d / ".log_path").write_text(
        "artifacts/copilot/training-logs/sft_20260704.log", encoding="utf-8"
    )
    out = read_training_log(repo, "artifacts/adapter-smoke", tail=10)
    assert out["present"] is True
    assert out["total_lines"] == 500
    assert out["lines"][-1] == "line 499"
    assert len(out["lines"]) == 10


def test_read_training_log_absent(repo: Path) -> None:
    # repo fixture already provides artifacts/adapter with no log inside.
    out = read_training_log(repo, "artifacts/adapter")
    assert out["present"] is False


# ---- preflight ------------------------------------------------------------
def test_preflight_flags_missing_data(repo: Path) -> None:
    r = train_ops.preflight(repo, method="sft", local=False)
    data = next(c for c in r["checks"] if c["id"] == "data")
    assert data["status"] == "fail"
    assert r["ok"] is False


def test_preflight_passes_with_good_sft_data(repo: Path) -> None:
    _write_jsonl(
        repo / "data" / "processed" / "train.jsonl",
        [
            {
                "messages": [
                    {"role": "user", "content": "hi"},
                    {"role": "assistant", "content": "hello"},
                ]
            }
        ],
    )
    r = train_ops.preflight(repo, method="sft", local=False)
    assert r["ok"] is True
    assert all(c["status"] != "fail" for c in r["checks"])


def test_preflight_dpo_rejects_non_preference_data(repo: Path) -> None:
    (repo / "configs" / "train_dpo.yaml").write_text(
        "model:\n  base_model: hf/test\ntraining:\n  epochs: 1\n", encoding="utf-8"
    )
    _write_jsonl(
        repo / "data" / "processed" / "preference_train.jsonl",
        [{"messages": [{"role": "user", "content": "hi"}]}],
    )  # not chosen/rejected
    r = train_ops.preflight(repo, method="dpo", local=False)
    data = next(c for c in r["checks"] if c["id"] == "data")
    assert data["status"] == "fail"
    assert "chosen/rejected" in data["detail"] or "preference" in data["detail"]


# ---- estimate -------------------------------------------------------------
def test_estimate_lora_fits(repo: Path) -> None:
    r = train_ops.estimate(
        repo,
        method="sft",
        overrides={
            "model.base_model": "meta-llama/Llama-3.1-8B",
            "model.quantization": "qlora-nf4",
        },
        gpu={"available": True, "vram_total_gb": 24},
    )
    assert r["known"] is True
    assert r["params_b"] == 8.0
    assert "4-bit" in r["quantization"]
    assert r["fits"] is True  # ~8*0.5 + overhead well under 24 GB


def test_estimate_full_finetune_is_large(repo: Path) -> None:
    r = train_ops.estimate(
        repo,
        method="sft",
        overrides={"model.base_model": "meta-llama/Llama-3.1-8B", "lora.enabled": False},
        gpu={"available": True, "vram_total_gb": 24},
    )
    assert r["known"] is True
    assert r["vram_gb"] > 100  # ~16x8B, cannot fit 24 GB
    assert r["fits"] is False
    assert any("exceeds" in w for w in r["warnings"])


def test_estimate_unknown_model(repo: Path) -> None:
    r = train_ops.estimate(repo, method="sft", gpu={})  # base is hf/test
    assert r["known"] is False


# ---- HTTP endpoints -------------------------------------------------------
def test_log_endpoint(repo: Path) -> None:
    d = repo / "artifacts" / "adapter"
    logs = repo / "artifacts" / "copilot" / "training-logs"
    logs.mkdir(parents=True)
    (logs / "sft_x.log").write_text("start\nboom\n", encoding="utf-8")
    (d / ".log_path").write_text("artifacts/copilot/training-logs/sft_x.log", encoding="utf-8")
    with _client(repo) as client:
        r = client.get("/api/train/log", params={"adapter_dir": "artifacts/adapter"})
        assert r.status_code == 200
        body = r.json()
        assert body["present"] is True
        assert body["lines"] == ["start", "boom"]


def test_preflight_endpoint(repo: Path) -> None:
    with _client(repo) as client:
        r = client.post("/api/train/preflight", json={"method": "sft", "local": False})
        assert r.status_code == 200
        body = r.json()
        assert body["kind"] == "train_preflight"
        assert any(c["id"] == "data" for c in body["checks"])


def test_estimate_endpoint(repo: Path) -> None:
    with _client(repo) as client:
        r = client.post(
            "/api/train/estimate",
            json={"method": "sft", "overrides": {"model.base_model": "meta-llama/Llama-3.1-8B"}},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["kind"] == "train_estimate"
        assert body["known"] is True
        assert body["params_b"] == 8.0


# ---- run config snapshot (reproducibility) --------------------------------
def test_run_config_absent(repo: Path) -> None:
    out = read_run_config(repo, "artifacts/adapter")
    assert out["present"] is False


def test_run_config_present(repo: Path) -> None:
    d = repo / "artifacts" / "adapter"
    (d / "run_config.yaml").write_text("model:\n  base_model: hf/x\n", encoding="utf-8")
    (d / "run_meta.json").write_text(
        json.dumps(
            {
                "dataset_hash": "abc123",
                "smoke_test": False,
                "dataset_splits": {"train": {"records": 5, "sha256": "de", "bytes": 9}},
            }
        ),
        encoding="utf-8",
    )
    out = read_run_config(repo, "artifacts/adapter")
    assert out["present"] is True
    assert "base_model" in out["yaml"]
    assert out["meta"]["dataset_hash"] == "abc123"


def test_run_config_endpoint(repo: Path) -> None:
    d = repo / "artifacts" / "adapter"
    (d / "run_config.yaml").write_text("training:\n  epochs: 3\n", encoding="utf-8")
    with _client(repo) as client:
        r = client.get("/api/train/run-config", params={"adapter_dir": "artifacts/adapter"})
        assert r.status_code == 200
        assert r.json()["present"] is True
        assert "epochs" in r.json()["yaml"]
