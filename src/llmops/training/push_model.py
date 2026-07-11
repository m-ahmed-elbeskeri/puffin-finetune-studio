"""Register a trained model in a model registry (MLflow by default).

CLI:
    python -m llmops.training.push_model \
        --model-dir artifacts/adapter \
        --name customer-support-llm \
        --alias candidate \
        --metrics artifacts/eval/metrics.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from llmops.common.errors import ProviderNotAvailableError
from llmops.common.logging import get_logger

log = get_logger(__name__)


def push_to_mlflow(
    model_dir: str | Path,
    *,
    name: str,
    alias: str = "candidate",
    metrics_path: str | Path | None = None,
    tags: dict[str, str] | None = None,
) -> str:
    """Register a model artifact in MLflow Model Registry. Returns the registered version URI."""
    try:
        import mlflow
    except ImportError as exc:  # pragma: no cover
        raise ProviderNotAvailableError(
            "mlflow is required for push_to_mlflow (pip install puffin-finetune-studio[mlflow])"
        ) from exc

    metrics: dict[str, float] = {}
    if metrics_path and Path(metrics_path).exists():
        loaded = json.loads(Path(metrics_path).read_text(encoding="utf-8"))
        metrics = {k: float(v) for k, v in loaded.items() if isinstance(v, (int, float))}

    with mlflow.start_run(run_name=f"{name}-register") as run:
        mlflow.log_artifacts(str(model_dir), artifact_path="model")
        if metrics:
            mlflow.log_metrics(metrics)
        if tags:
            mlflow.set_tags(tags)
        model_uri = f"runs:/{run.info.run_id}/model"
        result = mlflow.register_model(model_uri=model_uri, name=name)

        try:
            client = mlflow.MlflowClient()
            client.set_registered_model_alias(name, alias, result.version)
        except (AttributeError, RuntimeError) as exc:  # pragma: no cover
            log.warning("could not set alias %r on %s v%s: %s", alias, name, result.version, exc)

        log.info("registered %s version %s with alias %r", name, result.version, alias)
        return f"models:/{name}/{result.version}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Push model to registry.")
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--alias", default="candidate")
    parser.add_argument("--metrics", default=None)
    parser.add_argument("--tag", action="append", default=[], help="Repeated KEY=VALUE")
    parser.add_argument("--backend", default="mlflow", choices=["mlflow"])
    args = parser.parse_args(argv)

    tags: dict[str, str] = {}
    for kv in args.tag:
        if "=" not in kv:
            raise ValueError(f"invalid --tag {kv!r}; must be KEY=VALUE")
        k, v = kv.split("=", 1)
        tags[k] = v

    if args.backend == "mlflow":
        uri = push_to_mlflow(
            args.model_dir,
            name=args.name,
            alias=args.alias,
            metrics_path=args.metrics,
            tags=tags,
        )
        print(uri)
    return 0


if __name__ == "__main__":
    sys.exit(main())
