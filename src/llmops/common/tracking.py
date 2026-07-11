"""Experiment tracking abstraction: MLflow with a no-op fallback."""
from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from llmops.common.logging import get_logger

log = get_logger(__name__)


class _NoOpRun:
    info: Any = None

    def log_param(self, *args: Any, **kwargs: Any) -> None: ...
    def log_params(self, *args: Any, **kwargs: Any) -> None: ...
    def log_metric(self, *args: Any, **kwargs: Any) -> None: ...
    def log_metrics(self, *args: Any, **kwargs: Any) -> None: ...
    def log_artifact(self, *args: Any, **kwargs: Any) -> None: ...
    def log_artifacts(self, *args: Any, **kwargs: Any) -> None: ...
    def set_tag(self, *args: Any, **kwargs: Any) -> None: ...
    def set_tags(self, *args: Any, **kwargs: Any) -> None: ...


class Tracker:
    """MLflow wrapper with a no-op fallback when MLflow is not installed.

    Use as a long-lived object; call set_experiment() once and then start_run()
    around training/eval blocks.
    """

    def __init__(self, backend: str = "mlflow") -> None:
        self.backend = backend
        self._mlflow: Any = None
        if backend == "mlflow":
            try:
                import mlflow

                self._mlflow = mlflow
            except ImportError:
                log.warning("mlflow not installed; tracking disabled (falling back to no-op)")
                self.backend = "none"
        elif backend != "none":
            log.warning("unknown tracking backend %s; using no-op", backend)
            self.backend = "none"

    @property
    def enabled(self) -> bool:
        return self._mlflow is not None

    def set_experiment(self, name: str) -> None:
        if self._mlflow is not None:
            self._mlflow.set_experiment(name)

    @contextmanager
    def start_run(
        self,
        run_name: str | None = None,
        tags: dict[str, str] | None = None,
        nested: bool = False,
    ) -> Iterator[Any]:
        if self._mlflow is not None:
            with self._mlflow.start_run(
                run_name=run_name, tags=tags or {}, nested=nested
            ) as run:
                yield run
        else:
            yield _NoOpRun()

    def log_params(self, params: dict[str, Any]) -> None:
        if self._mlflow is not None:
            self._mlflow.log_params({k: str(v) for k, v in params.items()})

    def log_metrics(self, metrics: dict[str, float], step: int | None = None) -> None:
        if self._mlflow is not None:
            self._mlflow.log_metrics(metrics, step=step)

    def log_artifact(self, path: str, artifact_path: str | None = None) -> None:
        if self._mlflow is not None:
            self._mlflow.log_artifact(path, artifact_path=artifact_path)

    def log_artifacts(self, dir_path: str, artifact_path: str | None = None) -> None:
        if self._mlflow is not None:
            self._mlflow.log_artifacts(dir_path, artifact_path=artifact_path)

    def set_tags(self, tags: dict[str, Any]) -> None:
        if self._mlflow is not None:
            self._mlflow.set_tags({k: str(v) for k, v in tags.items()})

    def log_dict(self, payload: dict[str, Any], artifact_file: str) -> None:
        if self._mlflow is not None:
            self._mlflow.log_dict(payload, artifact_file)


def get_tracker(backend: str | None = None) -> Tracker:
    """Get a tracker. Reads PUFFIN_TRACKING_BACKEND env var if backend is None."""
    return Tracker(backend or os.environ.get("PUFFIN_TRACKING_BACKEND", "mlflow"))
