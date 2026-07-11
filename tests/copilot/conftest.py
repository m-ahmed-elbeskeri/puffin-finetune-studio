"""Shared fixtures for copilot tests.

Builds an isolated repo tree under tmp_path so tools that touch the
filesystem don't pollute the real project.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from copilot.backend.settings import Settings, reset_settings_for_tests
from copilot.backend.threads import ThreadStore
from copilot.backend.tools.registry import ToolContext


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Skeleton repo with the directories the tools expect."""
    (tmp_path / "data" / "raw").mkdir(parents=True)
    (tmp_path / "data" / "processed").mkdir(parents=True)
    (tmp_path / "artifacts" / "adapter").mkdir(parents=True)
    (tmp_path / "artifacts" / "eval").mkdir(parents=True)
    (tmp_path / "artifacts" / "serving").mkdir(parents=True)
    (tmp_path / "artifacts" / "_registry").mkdir(parents=True)
    (tmp_path / "configs").mkdir(parents=True)
    (tmp_path / "profiles").mkdir(parents=True)
    # Minimal data config so config_read works.
    (tmp_path / "configs" / "data.yaml").write_text(
        "name: test\nsources: [example]\n",
        encoding="utf-8",
    )
    (tmp_path / "configs" / "train.yaml").write_text(
        "model:\n  base_model: hf/test\ntraining:\n  epochs: 1\n",
        encoding="utf-8",
    )
    (tmp_path / "configs" / "eval.yaml").write_text(
        "gates:\n  min_task_score: 0.7\n",
        encoding="utf-8",
    )
    (tmp_path / "profiles" / "local.yaml").write_text(
        "storage: {backend: local}\nregistry: {backend: local}\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def ctx(repo: Path) -> ToolContext:
    return ToolContext(repo_root=repo, enable_dangerous=True)


@pytest.fixture
def settings(repo: Path, monkeypatch) -> Settings:
    monkeypatch.setenv("PUFFIN_REPO_ROOT", str(repo))
    monkeypatch.setenv("PUFFIN_COPILOT_DB", str(repo / "copilot" / "threads.sqlite3"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")  # we'll inject the provider
    monkeypatch.setenv("PUFFIN_COPILOT_ENABLE_DANGEROUS", "1")
    reset_settings_for_tests()
    s = Settings()
    return s


@pytest_asyncio.fixture
async def store(settings: Settings) -> ThreadStore:
    s = ThreadStore(settings.db_path)
    await s.initialize()
    return s


@pytest.fixture
def seed_finished_run(repo: Path) -> Path:
    """Plant a completed training run in artifacts/adapter."""
    d = repo / "artifacts" / "adapter"
    now = datetime.now(UTC)
    start = (now - timedelta(minutes=10)).isoformat(timespec="microseconds")
    end = (now - timedelta(minutes=5)).isoformat(timespec="microseconds")
    (d / "training_summary.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "method": "sft",
                "run_name": "test-run",
                "smoke_test": True,
                "base_model": "test/SmolLM2",
                "peft_method": "lora",
                "start_ts": start,
                "end_ts": end,
                "duration_s": 300.0,
                "total_steps": 4,
                "final_loss": 0.5,
                "best_eval_loss": 0.6,
                "trainable_params": 1024,
                "total_params": 1_000_000,
                "peak_vram_gb": 0.5,
                "adapter_dir": str(d),
            }
        )
    )
    rows = [
        {"ts": start, "step": 1, "loss": 1.0, "learning_rate": 2e-4, "epoch": 0.25},
        {"ts": start, "step": 2, "loss": 0.8, "learning_rate": 1.8e-4, "epoch": 0.5},
        {"ts": start, "step": 3, "loss": 0.65, "learning_rate": 1.5e-4, "epoch": 0.75},
        {"ts": end, "step": 4, "loss": 0.5, "learning_rate": 1.0e-4, "epoch": 1.0},
    ]
    (d / "training_metrics.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n",
    )
    return d


@pytest.fixture
def seed_active_run(repo: Path) -> Path:
    """Plant a running training run in artifacts/adapter-smoke."""
    d = repo / "artifacts" / "adapter-smoke"
    d.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    (d / "training_state.json").write_text(
        json.dumps(
            {
                "status": "running",
                "method": "sft",
                "run_name": "active-run",
                "smoke_test": True,
                "base_model": "test/SmolLM2",
                "peft_method": "lora",
                "pid": 9999,
                "start_ts": (now - timedelta(seconds=10)).isoformat(timespec="microseconds"),
                "last_update_ts": now.isoformat(timespec="microseconds"),
                "current_step": 3,
                "total_steps": 8,
                "current_epoch": 0.375,
                "total_epochs": 1.0,
                "current_loss": 0.9,
                "current_lr": 1.5e-4,
                "error": None,
            }
        )
    )
    (d / "training_metrics.jsonl").write_text(
        json.dumps({"step": 1, "loss": 1.1})
        + "\n"
        + json.dumps({"step": 2, "loss": 0.95})
        + "\n"
        + json.dumps({"step": 3, "loss": 0.9})
        + "\n",
    )
    return d
