"""YAML config loading with env-var interpolation, deep merge, and lineage hashing."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, TypeVar

import yaml
from pydantic import BaseModel

from llmops.common.errors import ConfigError

T = TypeVar("T", bound=BaseModel)

_ENV_VAR_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)(?::-(.*?))?\}")


def _interpolate_env(value: Any) -> Any:
    """Recursively expand ${ENV_VAR} or ${ENV_VAR:-default} patterns inside strings."""
    if isinstance(value, str):

        def replace(match: re.Match[str]) -> str:
            var_name, default = match.group(1), match.group(2)
            env_val = os.environ.get(var_name)
            if env_val is not None:
                return env_val
            if default is not None:
                return default
            return match.group(0)

        return _ENV_VAR_PATTERN.sub(replace, value)
    if isinstance(value, dict):
        return {k: _interpolate_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate_env(item) for item in value]
    return value


def load_yaml(path: str | Path) -> dict[str, Any]:
    """Load a YAML file and expand ${ENV_VAR} references."""
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"Expected YAML mapping at {path}, got {type(data).__name__}")
    return _interpolate_env(data)


def load_typed(path: str | Path, model: type[T]) -> T:
    """Load YAML and validate against a Pydantic model."""
    return model.model_validate(load_yaml(path))


def merge_configs(*configs: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge configs in order — later overrides earlier."""
    result: dict[str, Any] = {}
    for cfg in configs:
        _deep_merge(result, cfg)
    return result


def _deep_merge(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if (
            key in target
            and isinstance(target[key], dict)
            and isinstance(value, dict)
        ):
            _deep_merge(target[key], value)
        else:
            target[key] = value


def config_hash(cfg: dict[str, Any]) -> str:
    """Stable SHA256 hex digest of a config — used for lineage tagging."""
    serialized = json.dumps(cfg, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def flatten(cfg: dict[str, Any], prefix: str = "", sep: str = ".") -> dict[str, Any]:
    """Flatten a nested dict into dot-separated keys (useful for MLflow params)."""
    out: dict[str, Any] = {}
    for k, v in cfg.items():
        key = f"{prefix}{sep}{k}" if prefix else k
        if isinstance(v, dict):
            out.update(flatten(v, key, sep))
        elif isinstance(v, list):
            out[key] = json.dumps(v, default=str)
        else:
            out[key] = v
    return out
