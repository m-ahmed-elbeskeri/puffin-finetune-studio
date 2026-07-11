"""GCP provider: GCS storage + Vertex AI Model Registry + Vertex Pipelines + Endpoints.

All Google Cloud SDKs are imported lazily so this module is import-safe even
when the `gcp` extra is not installed. A clear ProviderNotAvailableError is
raised the moment a method that actually needs the SDK is called.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from llmops.common.errors import ProviderNotAvailableError
from llmops.common.logging import get_logger
from llmops.common.storage import StorageURI

log = get_logger(__name__)


def _import_gcs():
    try:
        from google.cloud import storage  # type: ignore

        return storage
    except ImportError as exc:  # pragma: no cover
        raise ProviderNotAvailableError(
            "google-cloud-storage not installed. "
            "Install puffin-finetune-studio[gcp]."
        ) from exc


def _import_aiplatform():
    try:
        from google.cloud import aiplatform  # type: ignore

        return aiplatform
    except ImportError as exc:  # pragma: no cover
        raise ProviderNotAvailableError(
            "google-cloud-aiplatform not installed. "
            "Install puffin-finetune-studio[gcp]."
        ) from exc


class GCSStorage:
    name = "gcs"

    def __init__(self, default_bucket: str | None = None) -> None:
        self.default_bucket = default_bucket or os.environ.get("PUFFIN_GCS_BUCKET")
        self._client: Any = None

    @property
    def client(self) -> Any:
        if self._client is None:
            storage = _import_gcs()
            self._client = storage.Client()
        return self._client

    def _split(self, remote_path: str) -> tuple[str, str]:
        u = StorageURI.parse(remote_path)
        if u.scheme == "gs":
            return u.bucket, u.path
        if not self.default_bucket:
            raise ValueError(
                f"remote path {remote_path!r} is not a gs:// URI and no default_bucket is set"
            )
        return self.default_bucket, remote_path.lstrip("/")

    def upload(self, local_path: str | Path, remote_path: str) -> str:
        bucket_name, blob_path = self._split(remote_path)
        bucket = self.client.bucket(bucket_name)
        local = Path(local_path)
        if local.is_dir():
            for f in local.rglob("*"):
                if f.is_file():
                    rel = f.relative_to(local).as_posix()
                    bucket.blob(f"{blob_path.rstrip('/')}/{rel}").upload_from_filename(str(f))
            return f"gs://{bucket_name}/{blob_path}"
        bucket.blob(blob_path).upload_from_filename(str(local))
        return f"gs://{bucket_name}/{blob_path}"

    def download(self, remote_path: str, local_path: str | Path) -> Path:
        bucket_name, blob_path = self._split(remote_path)
        bucket = self.client.bucket(bucket_name)
        local = Path(local_path)
        local.parent.mkdir(parents=True, exist_ok=True)
        blobs = list(bucket.list_blobs(prefix=blob_path))
        if not blobs:
            raise FileNotFoundError(f"no blobs at gs://{bucket_name}/{blob_path}")
        if len(blobs) == 1 and blobs[0].name == blob_path:
            blobs[0].download_to_filename(str(local))
            return local
        local.mkdir(parents=True, exist_ok=True)
        for b in blobs:
            rel = b.name[len(blob_path):].lstrip("/")
            target = local / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            b.download_to_filename(str(target))
        return local

    def exists(self, remote_path: str) -> bool:
        bucket_name, blob_path = self._split(remote_path)
        return self.client.bucket(bucket_name).blob(blob_path).exists()

    def list(self, prefix: str) -> list[str]:
        bucket_name, blob_path = self._split(prefix)
        return [b.name for b in self.client.list_blobs(bucket_name, prefix=blob_path)]

    def open_read(self, remote_path: str) -> bytes:
        bucket_name, blob_path = self._split(remote_path)
        return self.client.bucket(bucket_name).blob(blob_path).download_as_bytes()

    def open_write(self, remote_path: str, data: bytes) -> str:
        bucket_name, blob_path = self._split(remote_path)
        self.client.bucket(bucket_name).blob(blob_path).upload_from_string(data)
        return f"gs://{bucket_name}/{blob_path}"


class VertexAIModelRegistry:
    name = "vertex_ai"

    def __init__(self, project: str | None = None, location: str | None = None) -> None:
        self.project = project or os.environ.get("GCP_PROJECT_ID")
        self.location = location or os.environ.get("GCP_REGION", "us-central1")
        self._init = False

    def _ensure_init(self) -> None:
        if self._init:
            return
        aip = _import_aiplatform()
        aip.init(project=self.project, location=self.location)
        self._init = True

    def register_model(
        self,
        model_path: str | Path,
        *,
        name: str,
        version: str | None = None,
        metrics: dict[str, float] | None = None,
        tags: dict[str, str] | None = None,
    ) -> str:
        self._ensure_init()
        aip = _import_aiplatform()

        labels: dict[str, str] = {}
        if tags:
            labels = {k.lower(): str(v).lower() for k, v in tags.items()}
        if metrics:
            for k, v in metrics.items():
                labels[f"metric_{k.lower()}"] = str(round(float(v), 4))

        model = aip.Model.upload(
            display_name=name,
            artifact_uri=str(model_path),
            serving_container_image_uri="us-docker.pkg.dev/vertex-ai/prediction/pytorch-cpu.2-2:latest",
            labels=labels,
            version_aliases=["candidate"] if not version else [version, "candidate"],
        )
        log.info("registered Vertex Model %s (resource_name=%s)", name, model.resource_name)
        return model.resource_name

    def promote(self, name: str, version: str, alias: str) -> None:
        self._ensure_init()
        aip = _import_aiplatform()
        models = aip.Model.list(filter=f'display_name="{name}"')
        if not models:
            raise KeyError(f"no Vertex Model with display_name={name!r}")
        target = next(
            (
                m
                for m in models
                if m.version_aliases and version in m.version_aliases
            ),
            None,
        )
        if target is None:
            target = models[-1]
        target.update(version_aliases=[alias])
        log.info("promoted %s v%s to alias %s", name, version, alias)

    def get_model_uri(self, name: str, alias: str = "production") -> str:
        self._ensure_init()
        aip = _import_aiplatform()
        models = aip.Model.list(filter=f'display_name="{name}"')
        for m in models:
            if m.version_aliases and alias in m.version_aliases:
                return m.resource_name
        raise KeyError(f"no version of {name} has alias {alias!r}")

    def list_versions(self, name: str) -> list[dict[str, Any]]:
        self._ensure_init()
        aip = _import_aiplatform()
        return [
            {
                "version": m.version_id,
                "resource_name": m.resource_name,
                "aliases": list(m.version_aliases or []),
                "create_time": str(m.create_time),
            }
            for m in aip.Model.list(filter=f'display_name="{name}"')
        ]


class VertexAIPipelines:
    name = "vertex_pipelines"

    def __init__(self, project: str | None = None, location: str | None = None) -> None:
        self.project = project or os.environ.get("GCP_PROJECT_ID")
        self.location = location or os.environ.get("GCP_REGION", "us-central1")

    def submit_training_pipeline(
        self, config_path: str | Path, *, run_name: str | None = None
    ) -> str:
        aip = _import_aiplatform()
        aip.init(project=self.project, location=self.location)
        job = aip.PipelineJob(
            display_name=run_name or f"puffin-train-{Path(config_path).stem}",
            template_path=str(config_path),
            enable_caching=False,
        )
        job.submit()
        log.info("submitted Vertex pipeline %s", job.resource_name)
        return job.resource_name


class VertexAIEndpointDeployment:
    name = "vertex_endpoint"

    def __init__(self, project: str | None = None, location: str | None = None) -> None:
        self.project = project or os.environ.get("GCP_PROJECT_ID")
        self.location = location or os.environ.get("GCP_REGION", "us-central1")

    def deploy(self, model_ref: str, *, environment: str, traffic_pct: int = 100) -> str:
        aip = _import_aiplatform()
        aip.init(project=self.project, location=self.location)
        model = aip.Model(model_ref)
        endpoint_name = f"puffin-{environment}"
        endpoints = aip.Endpoint.list(filter=f'display_name="{endpoint_name}"')
        endpoint = endpoints[0] if endpoints else aip.Endpoint.create(display_name=endpoint_name)
        endpoint.deploy(
            model=model,
            traffic_percentage=traffic_pct,
            machine_type=os.environ.get("PUFFIN_VERTEX_MACHINE_TYPE", "n1-standard-4"),
        )
        return endpoint.resource_name

    def rollback(self, environment: str) -> str:
        aip = _import_aiplatform()
        aip.init(project=self.project, location=self.location)
        endpoint_name = f"puffin-{environment}"
        endpoints = aip.Endpoint.list(filter=f'display_name="{endpoint_name}"')
        if not endpoints:
            raise FileNotFoundError(f"no endpoint named {endpoint_name}")
        endpoint = endpoints[0]
        deployments = endpoint.list_models()
        if len(deployments) < 2:
            raise RuntimeError("no previous deployment to roll back to")
        prev = deployments[-2]
        endpoint.deploy(model=prev.model, traffic_percentage=100)
        return f"rolled back {endpoint.resource_name} to model {prev.model}"

    def get_endpoint_url(self, environment: str) -> str:
        aip = _import_aiplatform()
        aip.init(project=self.project, location=self.location)
        endpoints = aip.Endpoint.list(filter=f'display_name="puffin-{environment}"')
        if not endpoints:
            raise FileNotFoundError(f"no endpoint for env {environment}")
        return endpoints[0].resource_name
