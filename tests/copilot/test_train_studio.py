"""Training Studio — recipe/knob catalog, materialization, REST + tools."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
import yaml
from copilot.backend.app import create_app
from copilot.backend.settings import Settings
from copilot.backend.tools import ToolContext, registry
from copilot.backend.training_studio import (
    BASE_CONFIG,
    CLOUD_TARGETS,
    GROUP_ORDER,
    KNOBS,
    KNOBS_BY_PATH,
    RECIPES,
    StudioError,
    delete_custom_recipe,
    materialize,
    save_custom_recipe,
    studio_catalog,
    validate_overrides,
)
from starlette.testclient import TestClient


def test_custom_recipe_save_load_launch_delete(repo: Path) -> None:
    rec = save_custom_recipe(
        repo,
        name="My QLoRA",
        method="sft",
        overrides={"lora.r": 48, "training.epochs": 4},
        description="my go-to settings",
    )
    assert rec["category"] == "Your recipes"
    assert rec["id"] == "custom-sft-my-qlora"

    # It appears in the catalog (custom first) and can be materialized by id.
    cat = studio_catalog(repo)
    assert cat["recipes"][0]["id"] == rec["id"]
    assert "Your recipes" in cat["recipe_categories"]
    _rel, text = materialize(repo, method="sft", recipe_id=rec["id"])
    cfg = yaml.safe_load(text)
    assert cfg["lora"]["r"] == 48 and cfg["training"]["epochs"] == 4

    assert delete_custom_recipe(repo, rec["id"]) is True
    assert delete_custom_recipe(repo, rec["id"]) is False
    assert all(r["id"] != rec["id"] for r in studio_catalog(repo)["recipes"])


def test_custom_recipe_rejects_bad_overrides(repo: Path) -> None:
    with pytest.raises(StudioError):
        save_custom_recipe(repo, name="bad", method="sft", overrides={"not.a.knob": 1})
    with pytest.raises(StudioError):
        save_custom_recipe(repo, name="", method="sft", overrides={})


def test_catalog_exposes_cloud_targets(repo: Path) -> None:
    cat = studio_catalog(repo)
    ids = {t["id"] for t in cat["cloud_targets"]}
    assert {"local", "sagemaker", "vertex", "azureml"} <= ids
    sm = next(t for t in CLOUD_TARGETS if t["id"] == "sagemaker")
    assert "{config}" in sm["submit"] and sm["env_group"] == "aws"


def test_all_trl_methods_registered() -> None:
    from copilot.backend.tools.train import (
        METHOD_ADAPTER,
        METHOD_CONFIG,
        METHOD_MODULE,
        _adapter_rel,
    )

    methods = {"sft", "dpo", "kto", "reward", "grpo", "rloo"}
    assert set(BASE_CONFIG) == methods
    assert set(METHOD_MODULE) == methods
    assert set(METHOD_CONFIG) == methods
    assert set(METHOD_ADAPTER) == methods
    # Every method gets the shared knob surface, plus its own knobs exist.
    for m in methods:
        assert any(m in k["methods"] for k in KNOBS), f"{m} has no knobs"
    paths = {k["path"] for k in KNOBS}
    assert {"kto.beta", "grpo.num_generations", "rloo.num_generations"} <= paths
    # Smoke/adapter dir mapping the trainer configs expect.
    assert _adapter_rel("sft", True) == "adapter-smoke"
    assert _adapter_rel("kto", True) == "kto-smoke"
    assert _adapter_rel("reward", False) == "reward-model"


def test_new_methods_materialize(repo: Path) -> None:
    # Give the fixture a base config for each new method, then materialize.
    base = (
        "model:\n  base_model: hf/test\ntraining:\n  epochs: 1\n"
        "data:\n  train_path: data/processed/x.jsonl\n"
    )
    for m in ("kto", "reward", "grpo", "rloo"):
        (repo / "configs" / f"train_{m}.yaml").write_text(base, encoding="utf-8")
        _rel, text = materialize(repo, method=m, overrides={}, write=False)
        assert "base_model" in text


def test_cloud_submit_tokens_match_declared_fields() -> None:
    """Every {token} in a submit template must be `config` or a declared field
    key, so the /train form can fill it in — no orphan placeholders."""
    import re

    for t in CLOUD_TARGETS:
        if t["kind"] == "local":
            continue
        keys = {f["key"] for f in t.get("fields", [])}
        tokens = set(re.findall(r"\{(\w+)\}", t["submit"]))
        orphans = tokens - keys - {"config"}
        assert not orphans, f"{t['id']} has unfillable tokens: {orphans}"
        # Every declared field should actually be used by the command.
        unused = keys - tokens
        assert not unused, f"{t['id']} declares unused fields: {unused}"


# ---------------------------------------------------------------------------
# Catalog invariants
# ---------------------------------------------------------------------------
def test_recipe_catalog_is_self_consistent() -> None:
    from copilot.backend.training_studio import RECIPE_CATEGORIES

    ids = [r["id"] for r in RECIPES]
    assert len(ids) == len(set(ids))
    for r in RECIPES:
        assert "level" not in r, "the beginner/intermediate/advanced taxonomy is gone"
        assert r["category"] in RECIPE_CATEGORIES
        assert r["method"] in BASE_CONFIG
        assert r["tagline"] and r["description"]
        # Every recipe override must validate against the knob schema —
        # this is what keeps recipes from drifting away from the knobs.
        validate_overrides(r["overrides"], method=r["method"])


def test_knob_catalog_is_self_consistent() -> None:
    paths = [k["path"] for k in KNOBS]
    assert len(paths) == len(set(paths))
    for k in KNOBS:
        assert "level" not in k, "knobs use `essential`, not a difficulty level"
        assert isinstance(k["essential"], bool)
        assert k["group"] in GROUP_ORDER
        assert k["type"] in {"text", "int", "float", "bool", "select"}
        assert k["help"], f"knob {k['path']} needs help text"
        assert set(k["methods"]) <= {"sft", "dpo", "kto", "reward", "grpo", "rloo"}
        if k["type"] == "select":
            assert k["options"], f"select knob {k['path']} needs options"
        # Optional richer help: `recommended` is a non-empty string; every
        # `option_help` key must be a real option of that knob.
        if "recommended" in k:
            assert isinstance(k["recommended"], str) and k["recommended"].strip()
        if "option_help" in k:
            assert k["type"] == "select", f"{k['path']} option_help needs a select"
            assert set(k["option_help"]) <= set(k["options"]), (
                f"{k['path']} option_help has keys not in options"
            )
    # The default "essentials" view should be small and non-scary.
    essential_sft = [k for k in KNOBS if k["essential"] and "sft" in k["methods"]]
    assert 3 <= len(essential_sft) <= 10


def test_validate_overrides_rejects_bad_input() -> None:
    with pytest.raises(StudioError, match="unknown knob"):
        validate_overrides({"training.rm_rf": 1}, method="sft")
    with pytest.raises(StudioError, match="does not apply"):
        validate_overrides({"dpo.beta": 0.1}, method="sft")
    with pytest.raises(StudioError, match="invalid value"):
        validate_overrides({"training.epochs": "many"}, method="sft")
    with pytest.raises(StudioError, match="invalid value"):
        validate_overrides({"model.quantization": "5bit"}, method="sft")
    # Bools must be real bools, not truthy ints.
    with pytest.raises(StudioError, match="invalid value"):
        validate_overrides({"training.bf16": 1}, method="sft")


def test_validate_overrides_translates_virtual_selects() -> None:
    out = validate_overrides(
        {"model.quantization": "qlora-nf4", "lora.target_modules": "all-linear"},
        method="sft",
    )
    assert out["model.quantization"]["load_in_4bit"] is True
    assert out["model.quantization"]["bnb_4bit_quant_type"] == "nf4"
    assert "gate_proj" in out["lora.target_modules"]


# ---------------------------------------------------------------------------
# Materialization
# ---------------------------------------------------------------------------
def test_materialize_applies_overrides_and_writes(repo: Path) -> None:
    rel, text = materialize(
        repo,
        method="sft",
        overrides={
            "lora.r": 64,
            "training.learning_rate": 5e-5,
            "model.quantization": "qlora-nf4",
        },
    )
    assert rel == "configs/train_studio.yaml"
    written = (repo / rel).read_text(encoding="utf-8")
    assert written == text
    assert "Generated by Puffin Train Studio" in text
    cfg = yaml.safe_load(text)
    assert cfg["lora"]["r"] == 64
    assert cfg["training"]["learning_rate"] == 5e-5
    assert cfg["model"]["quantization"]["load_in_4bit"] is True
    # Untouched base values survive the merge.
    assert cfg["model"]["base_model"] == "hf/test"
    assert cfg["training"]["epochs"] == 1


def test_materialize_user_overrides_beat_recipe(repo: Path) -> None:
    _, text = materialize(
        repo,
        method="sft",
        recipe_id="style-tune",
        overrides={"training.epochs": 7},
    )
    cfg = yaml.safe_load(text)
    assert cfg["training"]["epochs"] == 7  # user wins
    assert cfg["lora"]["r"] == 16  # recipe still applied
    assert cfg["training"]["learning_rate"] == 1e-4


def test_materialize_rejects_bad_recipe_and_method(repo: Path) -> None:
    with pytest.raises(StudioError, match="unknown recipe"):
        materialize(repo, method="sft", recipe_id="turbo-mode")
    with pytest.raises(StudioError, match="method"):
        materialize(repo, method="rlhf")
    with pytest.raises(StudioError, match="dpo recipe"):
        materialize(repo, method="sft", recipe_id="dpo-align")
    # No dpo base config in the fixture repo.
    with pytest.raises(StudioError, match="base config not found"):
        materialize(repo, method="dpo")


def test_studio_catalog_reads_current_values(repo: Path) -> None:
    cat = studio_catalog(repo)
    assert cat["current"]["sft"]["model.base_model"] == "hf/test"
    assert cat["current"]["sft"]["training.epochs"] == 1
    # Virtual knob reverse-mapping: no quantization block → "none".
    assert cat["current"]["sft"]["model.quantization"] == "none"
    assert [r["id"] for r in cat["recipes"]] == [r["id"] for r in RECIPES]


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# AI tools (train_studio_recipes / train_studio_launch)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_studio_recipes_tool(ctx: ToolContext) -> None:
    out = await registry.invoke("train_studio_recipes", {}, ctx)
    assert out["kind"] == "studio_catalog"
    assert any(r["id"] == "qlora-single-gpu" for r in out["recipes"])
    assert out["current"]["sft"]["training.epochs"] == 1


@pytest.mark.asyncio
async def test_studio_launch_tool_is_gated(repo: Path) -> None:
    ctx = ToolContext(repo_root=repo, enable_dangerous=False)
    out = await registry.invoke("train_studio_launch", {"recipe": "smoke-test"}, ctx)
    assert out["kind"] == "error"
    assert "disabled" in out["message"].lower()


@pytest.mark.asyncio
async def test_studio_launch_tool_materializes_and_starts(
    ctx: ToolContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeProc:
        pid = 777

    async def fake_exec(*args: str, **kwargs: Any) -> _FakeProc:
        return _FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    # The test box has no trl/peft; skip the real dependency preflight.
    monkeypatch.setattr("copilot.backend.tools.train._missing_training_deps", lambda: [])
    out = await registry.invoke(
        "train_studio_launch",
        {"recipe": "style-tune", "overrides": {"lora.r": 24}, "smoke": True},
        ctx,
    )
    assert out["kind"] == "train_started"
    assert out["pid"] == 777
    assert out["config_path"] == "configs/train_studio.yaml"
    cfg = yaml.safe_load(
        (ctx.repo_root / "configs" / "train_studio.yaml").read_text(encoding="utf-8")
    )
    assert cfg["lora"]["r"] == 24  # user override wins
    assert cfg["training"]["learning_rate"] == 1e-4  # recipe applied


@pytest.mark.asyncio
async def test_studio_launch_tool_rejects_bad_input(ctx: ToolContext) -> None:
    out = await registry.invoke("train_studio_launch", {"overrides": {"evil.path": 1}}, ctx)
    assert out["kind"] == "error"
    assert "unknown knob" in out["message"]


def _make_settings(repo: Path, *, dangerous: bool) -> Settings:
    return Settings(
        anthropic_api_key="",
        repo_root=repo,
        db_path=repo / "artifacts" / "copilot" / "threads.sqlite3",
        enable_dangerous_tools=dangerous,
    )


def test_studio_endpoints_roundtrip(repo: Path) -> None:
    app = create_app(settings=_make_settings(repo, dangerous=False))
    with TestClient(app) as client:
        cat = client.get("/api/train/studio").json()
        assert cat["dangerous_enabled"] is False
        assert {k["path"] for k in cat["knobs"]} == set(KNOBS_BY_PATH)
        assert "gpu" in cat

        preview = client.post(
            "/api/train/preview",
            json={
                "method": "sft",
                "recipe": "domain-adapt",
                "overrides": {"lora.r": 48},
            },
        )
        assert preview.status_code == 200
        cfg = yaml.safe_load(preview.json()["yaml"])
        assert cfg["lora"]["r"] == 48
        assert cfg["training"]["neftune_noise_alpha"] == 5.0
        # Preview must NOT write the studio config.
        assert not (repo / "configs" / "train_studio.yaml").exists()

        bad = client.post(
            "/api/train/preview",
            json={
                "method": "sft",
                "overrides": {"nope.nope": 1},
            },
        )
        assert bad.status_code == 400
        assert "unknown knob" in bad.json()["detail"]


def test_launch_respects_dangerous_gate(repo: Path) -> None:
    app = create_app(settings=_make_settings(repo, dangerous=False))
    with TestClient(app) as client:
        r = client.post(
            "/api/train/launch",
            json={
                "method": "sft",
                "smoke": True,
                "recipe": "smoke-test",
            },
        )
        assert r.status_code == 200
        body = r.json()
        # The config materializes, but the registry gate blocks the spawn.
        assert body["launch"]["kind"] == "error"
        assert "disabled" in body["launch"]["message"].lower()
        assert (repo / "configs" / "train_studio.yaml").exists()


def test_launch_spawns_training_when_enabled(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spawned: dict[str, Any] = {}

    class _FakeProc:
        pid = 4242

    async def fake_exec(*args: str, **kwargs: Any) -> _FakeProc:
        spawned["args"] = list(args)
        return _FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr("copilot.backend.tools.train._missing_training_deps", lambda: [])

    app = create_app(settings=_make_settings(repo, dangerous=True))
    with TestClient(app) as client:
        r = client.post(
            "/api/train/launch",
            json={
                "method": "sft",
                "smoke": True,
                "overrides": {"training.epochs": 2},
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["launch"]["kind"] == "train_started"
        assert body["launch"]["pid"] == 4242
        assert body["launch"]["smoke"] is True
        assert body["config_path"] == "configs/train_studio.yaml"
        # The spawned command points at the materialized studio config.
        assert any("train_studio.yaml" in a for a in spawned["args"])
        assert "--smoke-test" in spawned["args"]
        cfg = yaml.safe_load((repo / "configs" / "train_studio.yaml").read_text(encoding="utf-8"))
        assert cfg["training"]["epochs"] == 2
