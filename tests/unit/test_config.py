from __future__ import annotations

import pytest
import yaml

from llmops.common.config import (
    config_hash,
    flatten,
    load_typed,
    load_yaml,
    merge_configs,
)
from llmops.common.errors import ConfigError


def test_load_yaml_missing(tmp_path):
    with pytest.raises(ConfigError):
        load_yaml(tmp_path / "nope.yaml")


def test_load_yaml_not_a_mapping(tmp_path):
    p = tmp_path / "list.yaml"
    p.write_text("- a\n- b\n")
    with pytest.raises(ConfigError):
        load_yaml(p)


def test_env_interpolation_with_default(tmp_path, monkeypatch):
    monkeypatch.delenv("PUFFIN_TEST_X", raising=False)
    p = tmp_path / "c.yaml"
    p.write_text("value: ${PUFFIN_TEST_X:-fallback}\n")
    assert load_yaml(p) == {"value": "fallback"}


def test_env_interpolation_set(tmp_path, monkeypatch):
    monkeypatch.setenv("PUFFIN_TEST_X", "real")
    p = tmp_path / "c.yaml"
    p.write_text("value: ${PUFFIN_TEST_X:-fallback}\n")
    assert load_yaml(p) == {"value": "real"}


def test_env_interpolation_recursive(tmp_path, monkeypatch):
    monkeypatch.setenv("PUFFIN_REGION", "eu-west-1")
    p = tmp_path / "c.yaml"
    p.write_text(
        yaml.safe_dump(
            {"a": {"region": "${PUFFIN_REGION}"}, "b": ["${PUFFIN_REGION}", "x"]}
        )
    )
    assert load_yaml(p) == {"a": {"region": "eu-west-1"}, "b": ["eu-west-1", "x"]}


def test_merge_configs_deep():
    a = {"x": {"a": 1, "b": 2}, "y": 1}
    b = {"x": {"b": 99, "c": 3}}
    assert merge_configs(a, b) == {"x": {"a": 1, "b": 99, "c": 3}, "y": 1}


def test_config_hash_stable():
    a = {"a": 1, "b": [2, 3]}
    b = {"b": [2, 3], "a": 1}
    assert config_hash(a) == config_hash(b)


def test_flatten_with_list():
    assert flatten({"a": {"b": 1}, "c": [1, 2]})["a.b"] == 1
    assert flatten({"a": [1, 2]})["a"] == "[1, 2]"


def test_load_typed():
    from pydantic import BaseModel

    class M(BaseModel):
        name: str
        x: int = 0

    import tempfile
    from pathlib import Path

    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        f.write("name: foo\nx: 7\n")
        path = Path(f.name)

    try:
        m = load_typed(path, M)
        assert m.name == "foo"
        assert m.x == 7
    finally:
        path.unlink()
