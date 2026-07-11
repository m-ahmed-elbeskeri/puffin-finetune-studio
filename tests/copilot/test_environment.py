"""Environment doctor + training-run visibility fixes."""
from __future__ import annotations

import json

import pytest

from copilot.backend import environment as env
from copilot.backend.tools import train as train_tools


def test_check_environment_shape():
    report = env.check_environment()
    assert report["kind"] == "environment"
    assert report["python"]
    ids = {g["id"] for g in report["groups"]}
    assert {"train", "aws", "gcp", "azure", "quantization"} <= ids
    train_group = next(g for g in report["groups"] if g["id"] == "train")
    assert train_group["install_command"] == 'pip install -e ".[train]"'
    assert train_group["total"] == len(train_group["packages"])
    # ready reflects whether every package imports
    assert train_group["ready"] == (train_group["installed_count"] == train_group["total"])


def test_install_command_for_explicit_packages():
    quant = next(g for g in env.GROUPS if g["id"] == "quantization")
    assert env._install_command(quant) == "pip install bitsandbytes"
    argv, _cwd = env._install_argv(quant)
    assert argv[-1] == "bitsandbytes"


def test_install_runs_from_platform_root_not_cwd():
    """The [train] extra must install from the platform's pyproject dir, never
    the selected data project (which has no pyproject.toml)."""
    root = env._platform_root()
    assert root is not None and (root / "pyproject.toml").exists()
    train = next(g for g in env.GROUPS if g["id"] == "train")
    argv, cwd = env._install_argv(train)
    assert cwd == root
    assert argv[-2:] == ["-e", ".[train]"]


@pytest.mark.asyncio
async def test_stream_install_rejects_unknown_group():
    events = [ev async for ev in env.stream_install("nope")]
    assert events == [("error", "unknown environment group: nope")]


def test_derive_stage():
    assert train_tools._derive_stage("completed", 5, 5) == "completed"
    assert train_tools._derive_stage("failed", None, None) == "failed"
    assert train_tools._derive_stage("starting", None, None) == "loading model and data"
    assert "step 3 of 8" in train_tools._derive_stage("running", 3, 8)


def test_pid_alive_false_for_dead_pid():
    # PID 2**31-1 is effectively guaranteed not to exist.
    assert train_tools._pid_alive(2**31 - 1) is False
    assert train_tools._pid_alive(None) is False
    assert train_tools._pid_alive("notanint") is False


def test_serialise_flips_dead_run_to_failed(tmp_path):
    d = tmp_path / "adapter-smoke"
    d.mkdir()
    (d / "training_state.json").write_text(json.dumps({
        "status": "running", "method": "sft", "smoke_test": True,
        "pid": 2**31 - 1,  # dead
        "start_ts": "2020-01-01T00:00:00+00:00",
        "last_update_ts": "2020-01-01T00:00:00+00:00",
        "current_step": None,
    }), encoding="utf-8")
    run = train_tools._serialise_run(d, repo=tmp_path)
    assert run["status"] == "failed"
    assert run["error"] and "exited" in run["error"]
    # elapsed_s computed from start_ts even without a summary
    assert run["elapsed_s"] and run["elapsed_s"] > 0


def test_missing_training_deps_reports_uninstalled():
    missing = train_tools._missing_training_deps()
    # trl is not part of the base install; if it's absent it must be reported.
    import importlib.util
    if importlib.util.find_spec("trl") is None:
        assert "trl" in missing
