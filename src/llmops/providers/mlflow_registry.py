"""MLflow registry adapter (cloud-portable)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from llmops.common.errors import ProviderNotAvailableError
from llmops.common.logging import get_logger

log = get_logger(__name__)


def _import_mlflow():
    try:
        import mlflow  # type: ignore

        return mlflow
    except ImportError as exc:  # pragma: no cover
        raise ProviderNotAvailableError(
            "mlflow not installed. Install puffin-finetune-studio[mlflow]."
        ) from exc


class MLflowRegistry:
    name = "mlflow"

    def __init__(self, tracking_uri: str | None = None) -> None:
        self.tracking_uri = tracking_uri or os.environ.get("MLFLOW_TRACKING_URI", "file:./mlruns")
        self._mlflow: Any = None

    @property
    def mlflow(self) -> Any:
        if self._mlflow is None:
            self._mlflow = _import_mlflow()
            self._mlflow.set_tracking_uri(self.tracking_uri)
        return self._mlflow

    def register_model(
        self,
        model_path: str | Path,
        *,
        name: str,
        version: str | None = None,
        metrics: dict[str, float] | None = None,
        tags: dict[str, str] | None = None,
    ) -> str:
        with self.mlflow.start_run(run_name=f"{name}-register") as run:
            self.mlflow.log_artifacts(str(model_path), artifact_path="model")
            if metrics:
                self.mlflow.log_metrics(metrics)
            if tags:
                self.mlflow.set_tags(tags)
            model_uri = f"runs:/{run.info.run_id}/model"
            result = self.mlflow.register_model(model_uri=model_uri, name=name)
            try:
                self.mlflow.MlflowClient().set_registered_model_alias(
                    name, "candidate", result.version
                )
            except Exception as exc:  # pragma: no cover
                log.warning("alias set failed: %s", exc)
            return f"models:/{name}/{result.version}"

    def promote(self, name: str, version: str, alias: str) -> None:
        self.mlflow.MlflowClient().set_registered_model_alias(name, alias, version)
        log.info("MLflow: %s v%s alias=%s", name, version, alias)

    def get_model_uri(self, name: str, alias: str = "production") -> str:
        client = self.mlflow.MlflowClient()
        model_version = client.get_model_version_by_alias(name, alias)
        return f"models:/{name}/{model_version.version}"

    def list_versions(self, name: str) -> list[dict[str, Any]]:
        client = self.mlflow.MlflowClient()
        return [
            {
                "version": v.version,
                "current_stage": v.current_stage,
                "tags": dict(v.tags or {}),
                "creation_timestamp": v.creation_timestamp,
            }
            for v in client.search_model_versions(f"name='{name}'")
        ]
