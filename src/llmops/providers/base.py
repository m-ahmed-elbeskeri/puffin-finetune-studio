"""Provider Protocols. Every backend in `llmops.providers.*` implements these."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class StorageBackend(Protocol):
    """Bytes-and-files storage abstraction."""

    name: str

    def upload(self, local_path: str | Path, remote_path: str) -> str: ...
    def download(self, remote_path: str, local_path: str | Path) -> Path: ...
    def exists(self, remote_path: str) -> bool: ...
    def list(self, prefix: str) -> list[str]: ...
    def open_read(self, remote_path: str) -> bytes: ...
    def open_write(self, remote_path: str, data: bytes) -> str: ...


class ModelRegistry(Protocol):
    """Versioned model registry contract."""

    name: str

    def register_model(
        self,
        model_path: str | Path,
        *,
        name: str,
        version: str | None = None,
        metrics: dict[str, float] | None = None,
        tags: dict[str, str] | None = None,
    ) -> str: ...

    def promote(self, name: str, version: str, alias: str) -> None: ...
    def get_model_uri(self, name: str, alias: str = "production") -> str: ...
    def list_versions(self, name: str) -> list[dict[str, Any]]: ...


class PipelineBackend(Protocol):
    """Container-based pipeline orchestration."""

    name: str

    def submit_training_pipeline(
        self, config_path: str | Path, *, run_name: str | None = None
    ) -> str: ...


class DeploymentBackend(Protocol):
    """Inference deployment contract."""

    name: str

    def deploy(self, model_ref: str, *, environment: str, traffic_pct: int = 100) -> str: ...
    def rollback(self, environment: str) -> str: ...
    def get_endpoint_url(self, environment: str) -> str: ...
