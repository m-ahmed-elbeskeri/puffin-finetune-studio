from __future__ import annotations

import pytest

from llmops.providers.local import LocalDeployment, LocalRegistry, LocalStorage


def test_local_storage_roundtrip(tmp_path):
    s = LocalStorage(root=tmp_path / "art")
    src = tmp_path / "src.txt"
    src.write_text("hello", encoding="utf-8")

    s.upload(src, "models/x/file.txt")
    assert s.exists("models/x/file.txt")
    assert s.list("models")[0].endswith("file.txt")
    out = s.open_read("models/x/file.txt")
    assert out == b"hello"


def test_local_storage_directory_upload(tmp_path):
    s = LocalStorage(root=tmp_path / "art")
    d = tmp_path / "dir"
    (d / "sub").mkdir(parents=True)
    (d / "a.txt").write_text("A")
    (d / "sub" / "b.txt").write_text("B")
    s.upload(d, "model")
    assert s.exists("model/a.txt")
    assert s.exists("model/sub/b.txt")


def test_local_storage_open_write_read(tmp_path):
    s = LocalStorage(root=tmp_path / "art")
    s.open_write("a/b/c.bin", b"\x00\x01")
    assert s.open_read("a/b/c.bin") == b"\x00\x01"


def test_local_registry_register_and_promote(tmp_path):
    reg = LocalRegistry(root=tmp_path / "art")
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "weights.bin").write_text("w")

    uri = reg.register_model(model_dir, name="my-model", metrics={"score": 0.9})
    assert uri.startswith("local:my-model")

    versions = reg.list_versions("my-model")
    assert len(versions) == 1

    version = versions[0]["version"]
    reg.promote("my-model", version, alias="staging")
    assert reg.get_model_uri("my-model", "staging").endswith(version)


def test_local_registry_promote_unknown_version_raises(tmp_path):
    reg = LocalRegistry(root=tmp_path / "art")
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    reg.register_model(model_dir, name="m")
    with pytest.raises(ValueError):
        reg.promote("m", "999", "production")


def test_local_registry_multiple_versions(tmp_path):
    reg = LocalRegistry(root=tmp_path / "art")
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "weights.bin").write_text("w")

    reg.register_model(model_dir, name="m")
    reg.register_model(model_dir, name="m")
    versions = reg.list_versions("m")
    assert {v["version"] for v in versions} == {"1", "2"}


def test_local_deployment_writes_manifest(tmp_path):
    dep = LocalDeployment(root=tmp_path / "art")
    out = dep.deploy("local:my-model/v1", environment="staging", traffic_pct=100)
    assert out.startswith("local-deployment://")
    assert (tmp_path / "art" / "_deployments" / "staging.json").exists()


def test_local_deployment_endpoint_url():
    dep = LocalDeployment(root="/tmp/x")
    url = dep.get_endpoint_url("staging")
    assert url.startswith("http://")
