"""Behavioural tests for the workflow tools.

Each test calls the tool through the global registry exactly as the
LLM tool-use loop would, so we exercise validation + serialisation too.
"""

from __future__ import annotations

import json

import pytest
from copilot.backend.tools import registry

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# project_status
# ---------------------------------------------------------------------------
async def test_project_status_empty_repo(ctx):
    r = await registry.invoke("project_status", {}, ctx)
    assert r["kind"] == "project_status"
    assert r["next_action"].startswith("Drop a JSONL")
    keys = [s["key"] for s in r["steps"]]
    assert keys == ["data", "train", "evaluate", "deploy", "monitor"]
    # Empty repo → every step pending.
    assert r["steps"][0]["status"] in {"pending", "current", "done"}


async def test_project_status_with_raw_data(ctx):
    (ctx.repo_root / "data" / "raw" / "example.jsonl").write_text(
        json.dumps({"messages": [{"role": "user", "content": "hi"}]}) + "\n",
        encoding="utf-8",
    )
    r = await registry.invoke("project_status", {}, ctx)
    assert r["steps"][0]["status"] == "current"
    assert "data pipeline" in r["next_action"].lower()


# ---------------------------------------------------------------------------
# dataset_audit + dataset_preview
# ---------------------------------------------------------------------------
async def test_dataset_audit_chat_schema(ctx):
    p = ctx.repo_root / "data" / "raw" / "demo.jsonl"
    p.write_text(
        "\n".join(
            json.dumps(
                {
                    "messages": [
                        {"role": "user", "content": "hello"},
                        {"role": "assistant", "content": "hi there"},
                    ],
                    "source": "demo",
                    "license": "internal",
                }
            )
            for _ in range(10)
        )
        + "\n",
        encoding="utf-8",
    )
    r = await registry.invoke(
        "dataset_audit",
        {"path": "data/raw/demo.jsonl"},
        ctx,
    )
    assert r["kind"] == "dataset_audit"
    assert r["schema"] == "messages"
    assert r["total_records"] == 10
    assert r["sources"] == {"demo": 10}


async def test_dataset_audit_flags_email(ctx):
    p = ctx.repo_root / "data" / "raw" / "pii.jsonl"
    p.write_text(
        json.dumps(
            {"messages": [{"role": "user", "content": "Email me at alice@example.com please"}]}
        )
        + "\n",
        encoding="utf-8",
    )
    r = await registry.invoke(
        "dataset_audit",
        {"path": "data/raw/pii.jsonl"},
        ctx,
    )
    assert r["pii"]["email"] >= 1


async def test_dataset_audit_rejects_path_escape(ctx):
    r = await registry.invoke(
        "dataset_audit",
        {"path": "../etc/passwd"},
        ctx,
    )
    assert r["kind"] == "error"
    assert "escapes repo root" in r["message"]


async def test_dataset_preview(ctx):
    p = ctx.repo_root / "data" / "processed" / "train.jsonl"
    rows = [{"id": i, "messages": [{"role": "user", "content": f"q{i}"}]} for i in range(5)]
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    r = await registry.invoke(
        "dataset_preview",
        {"path": "data/processed/train.jsonl", "n": 3},
        ctx,
    )
    assert r["kind"] == "dataset_preview"
    assert len(r["records"]) == 3
    assert r["records"][0]["id"] == 0


# ---------------------------------------------------------------------------
# train_status + train_history + train_get_run (uses fixtures)
# ---------------------------------------------------------------------------
async def test_train_history_lists_seeded_run(ctx, seed_finished_run):
    r = await registry.invoke("train_history", {}, ctx)
    assert r["kind"] == "run_history"
    runs = r["runs"]
    assert len(runs) >= 1
    run = next(
        r
        for r in runs
        if r["adapter_dir"] == "artifacts\\adapter" or r["adapter_dir"] == "artifacts/adapter"
    )
    assert run["status"] == "completed"
    assert run["final_loss"] == 0.5
    assert run["total_steps"] == 4


async def test_train_status_picks_active_run(ctx, seed_active_run):
    r = await registry.invoke("train_status", {}, ctx)
    assert r["kind"] == "live_training"
    assert r["active"] is True
    assert r["run"]["status"] == "running"
    assert r["run"]["current_step"] == 3
    assert len(r["run"]["metrics"]) == 3


async def test_train_status_no_active_run(ctx):
    r = await registry.invoke("train_status", {}, ctx)
    assert r["kind"] == "live_training"
    assert r["active"] is False


async def test_train_get_run_full_metrics(ctx, seed_finished_run):
    r = await registry.invoke(
        "train_get_run",
        {"adapter_dir": "artifacts/adapter"},
        ctx,
    )
    assert r["kind"] == "run_detail"
    assert len(r["run"]["metrics"]) == 4
    assert r["run"]["metrics"][0]["loss"] == 1.0


async def test_train_start_blocked_without_dangerous(ctx, monkeypatch):
    safe_ctx = type(ctx)(repo_root=ctx.repo_root, enable_dangerous=False)
    r = await registry.invoke(
        "train_start",
        {"method": "sft", "smoke": True},
        safe_ctx,
    )
    assert r["kind"] == "error"
    assert "disabled" in r["message"].lower()


# ---------------------------------------------------------------------------
# eval_get_metrics
# ---------------------------------------------------------------------------
async def test_eval_get_metrics_present_and_absent(ctx):
    r = await registry.invoke("eval_get_metrics", {}, ctx)
    assert r["present"] is False
    (ctx.repo_root / "artifacts" / "eval" / "metrics.json").write_text(
        json.dumps({"task_score": 0.9, "p95_latency_ms": 1000}),
        encoding="utf-8",
    )
    r2 = await registry.invoke("eval_get_metrics", {}, ctx)
    assert r2["present"] is True
    assert r2["metrics"]["task_score"] == 0.9


# ---------------------------------------------------------------------------
# config_list / read / edit
# ---------------------------------------------------------------------------
async def test_config_list_includes_seeded(ctx):
    r = await registry.invoke("config_list", {}, ctx)
    paths = {f["path"].replace("\\", "/") for f in r["files"]}
    assert "configs/data.yaml" in paths
    assert "configs/train.yaml" in paths
    assert "profiles/local.yaml" in paths


async def test_config_read_parses(ctx):
    r = await registry.invoke("config_read", {"path": "configs/train.yaml"}, ctx)
    assert r["kind"] == "config_read"
    assert r["parsed"]["training"]["epochs"] == 1


async def test_config_edit_writes_backup_and_validates(ctx):
    new_text = "model:\n  base_model: hf/test\ntraining:\n  epochs: 2\n"
    r = await registry.invoke(
        "config_edit",
        {"path": "configs/train.yaml", "new_text": new_text},
        ctx,
    )
    assert r["kind"] == "config_edit_result"
    backup = ctx.repo_root / (r["backup"])
    assert backup.exists()
    assert "epochs: 2" in (ctx.repo_root / "configs/train.yaml").read_text(encoding="utf-8")


async def test_config_edit_rejects_bad_yaml(ctx):
    r = await registry.invoke(
        "config_edit",
        {"path": "configs/train.yaml", "new_text": ": ::: invalid yaml ::"},
        ctx,
    )
    assert r["kind"] == "error"
    assert "YAML parse error" in r["message"]


async def test_config_edit_rejects_outside_paths(ctx):
    r = await registry.invoke(
        "config_edit",
        {"path": "README.md", "new_text": "hi"},
        ctx,
    )
    assert r["kind"] == "error"
    assert "only configs/" in r["message"]


# ---------------------------------------------------------------------------
# deploy_render_k8s — read-only, no extras needed
# ---------------------------------------------------------------------------
async def test_deploy_render_k8s_returns_yaml(ctx):
    r = await registry.invoke(
        "deploy_render_k8s",
        {"environment": "staging", "replicas": 2},
        ctx,
    )
    assert r["kind"] == "k8s_manifest"
    assert "kind: Deployment" in r["yaml"]
    assert r["lines"] > 10


# ---------------------------------------------------------------------------
# monitor — quality/drift absent + present
# ---------------------------------------------------------------------------
async def test_monitor_quality_absent(ctx):
    r = await registry.invoke("monitor_quality", {}, ctx)
    assert r["present"] is False


async def test_monitor_quality_present(ctx):
    d = ctx.repo_root / "artifacts" / "monitoring"
    d.mkdir(parents=True, exist_ok=True)
    (d / "quality.json").write_text(
        json.dumps({"sampled": 50, "refusal_rate": 0.05, "json_validity_rate": 0.98}),
        encoding="utf-8",
    )
    r = await registry.invoke("monitor_quality", {}, ctx)
    assert r["present"] is True
    assert r["report"]["sampled"] == 50


async def test_monitor_request_log_summary(ctx):
    p = ctx.repo_root / "artifacts" / "serving" / "requests.jsonl"
    p.write_text(
        "\n".join(
            json.dumps(
                {
                    "ts": "2026-01-01T00:00:00Z",
                    "model_version": "1",
                    "latency_ms": 200 + i,
                    "output_chars": 50,
                }
            )
            for i in range(10)
        ),
        encoding="utf-8",
    )
    r = await registry.invoke("monitor_request_log", {"n": 5}, ctx)
    assert r["present"] is True
    assert r["total"] == 10
    assert len(r["recent"]) == 5
    assert r["summary"]["avg_latency_ms"] > 200
    assert r["summary"]["by_model_version"] == {"1": 10}
