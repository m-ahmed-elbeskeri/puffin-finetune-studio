"""Azure provider: Blob storage + Azure ML model registry + online endpoints.

Lazy-imports azure-storage-blob and azure-ai-ml.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from llmops.common.errors import ProviderNotAvailableError
from llmops.common.logging import get_logger
from llmops.common.storage import StorageURI

log = get_logger(__name__)


def _import_blob():
    try:
        from azure.storage.blob import BlobServiceClient  # type: ignore

        return BlobServiceClient
    except ImportError as exc:  # pragma: no cover
        raise ProviderNotAvailableError(
            "azure-storage-blob not installed. Install puffin-finetune-studio[azure]."
        ) from exc


def _import_azureml():
    try:
        from azure.ai.ml import MLClient  # type: ignore
        from azure.ai.ml.entities import (  # type: ignore
            ManagedOnlineDeployment,
            ManagedOnlineEndpoint,
            Model,
        )
        from azure.identity import DefaultAzureCredential  # type: ignore

        return {
            "MLClient": MLClient,
            "Model": Model,
            "ManagedOnlineEndpoint": ManagedOnlineEndpoint,
            "ManagedOnlineDeployment": ManagedOnlineDeployment,
            "DefaultAzureCredential": DefaultAzureCredential,
        }
    except ImportError as exc:  # pragma: no cover
        raise ProviderNotAvailableError(
            "azure-ai-ml + azure-identity not installed. Install puffin-finetune-studio[azure]."
        ) from exc


class AzureBlobStorage:
    name = "azure_blob"

    def __init__(
        self,
        account_url: str | None = None,
        default_container: str | None = None,
    ) -> None:
        self.account_url = account_url or os.environ.get("PUFFIN_AZURE_ACCOUNT_URL")
        self.default_container = default_container or os.environ.get("PUFFIN_AZURE_CONTAINER")
        self._svc: Any = None

    @property
    def svc(self) -> Any:
        if self._svc is None:
            from azure.identity import DefaultAzureCredential  # type: ignore

            BlobServiceClient = _import_blob()
            self._svc = BlobServiceClient(
                account_url=self.account_url,
                credential=DefaultAzureCredential(),
            )
        return self._svc

    def _split(self, remote_path: str) -> tuple[str, str]:
        u = StorageURI.parse(remote_path)
        if u.scheme == "az":
            return u.bucket, u.path
        if not self.default_container:
            raise ValueError(f"remote {remote_path!r} is not az:// and no default_container set")
        return self.default_container, remote_path.lstrip("/")

    def upload(self, local_path: str | Path, remote_path: str) -> str:
        container, blob = self._split(remote_path)
        client = self.svc.get_container_client(container)
        local = Path(local_path)
        if local.is_dir():
            for f in local.rglob("*"):
                if f.is_file():
                    rel = f.relative_to(local).as_posix()
                    with f.open("rb") as fh:
                        client.upload_blob(
                            name=f"{blob.rstrip('/')}/{rel}", data=fh, overwrite=True
                        )
            return f"az://{container}/{blob}"
        with local.open("rb") as fh:
            client.upload_blob(name=blob, data=fh, overwrite=True)
        return f"az://{container}/{blob}"

    def download(self, remote_path: str, local_path: str | Path) -> Path:
        container, blob = self._split(remote_path)
        client = self.svc.get_container_client(container)
        local = Path(local_path)
        local.parent.mkdir(parents=True, exist_ok=True)
        blobs = list(client.list_blobs(name_starts_with=blob))
        if not blobs:
            raise FileNotFoundError(f"no blobs at az://{container}/{blob}")
        if len(blobs) == 1 and blobs[0].name == blob:
            with local.open("wb") as fh:
                fh.write(client.download_blob(blob).readall())
            return local
        local.mkdir(parents=True, exist_ok=True)
        for b in blobs:
            rel = b.name[len(blob) :].lstrip("/")
            target = local / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("wb") as fh:
                fh.write(client.download_blob(b.name).readall())
        return local

    def exists(self, remote_path: str) -> bool:
        container, blob = self._split(remote_path)
        return self.svc.get_container_client(container).get_blob_client(blob).exists()

    def list(self, prefix: str) -> list[str]:
        container, blob = self._split(prefix)
        return [
            b.name
            for b in self.svc.get_container_client(container).list_blobs(name_starts_with=blob)
        ]

    def open_read(self, remote_path: str) -> bytes:
        container, blob = self._split(remote_path)
        return self.svc.get_container_client(container).download_blob(blob).readall()

    def open_write(self, remote_path: str, data: bytes) -> str:
        container, blob = self._split(remote_path)
        self.svc.get_container_client(container).upload_blob(name=blob, data=data, overwrite=True)
        return f"az://{container}/{blob}"


class AzureMLRegistry:
    name = "azure_ml"

    def __init__(
        self,
        subscription_id: str | None = None,
        resource_group: str | None = None,
        workspace_name: str | None = None,
    ) -> None:
        self.subscription_id = subscription_id or os.environ.get("AZURE_SUBSCRIPTION_ID")
        self.resource_group = resource_group or os.environ.get("AZURE_RESOURCE_GROUP")
        self.workspace_name = workspace_name or os.environ.get("AZUREML_WORKSPACE_NAME")
        self._client: Any = None

    @property
    def client(self) -> Any:
        if self._client is None:
            azureml = _import_azureml()
            self._client = azureml["MLClient"](
                credential=azureml["DefaultAzureCredential"](),
                subscription_id=self.subscription_id,
                resource_group_name=self.resource_group,
                workspace_name=self.workspace_name,
            )
        return self._client

    def register_model(
        self,
        model_path: str | Path,
        *,
        name: str,
        version: str | None = None,
        metrics: dict[str, float] | None = None,
        tags: dict[str, str] | None = None,
    ) -> str:
        azureml = _import_azureml()
        model = azureml["Model"](
            path=str(model_path),
            name=name,
            type="custom_model",
            version=version,
            tags={
                **(tags or {}),
                **({f"metric_{k}": str(v) for k, v in (metrics or {}).items()}),
            },
        )
        registered = self.client.models.create_or_update(model)
        log.info("registered Azure ML Model %s version=%s", name, registered.version)
        return f"azureml:{name}:{registered.version}"

    def promote(self, name: str, version: str, alias: str) -> None:
        # Azure ML uses tags as labels for promotion; full alias support is
        # done via Azure ML registries (separate object).
        model = self.client.models.get(name=name, version=version)
        tags = dict(model.tags or {})
        tags["alias"] = alias
        model.tags = tags
        self.client.models.create_or_update(model)
        log.info("set tag alias=%s on Azure ML %s v%s", alias, name, version)

    def get_model_uri(self, name: str, alias: str = "production") -> str:
        for m in self.client.models.list(name=name):
            if (m.tags or {}).get("alias") == alias:
                return f"azureml:{name}:{m.version}"
        raise KeyError(f"no version of {name} has alias {alias!r}")

    def list_versions(self, name: str) -> list[dict[str, Any]]:
        return [
            {
                "version": m.version,
                "tags": dict(m.tags or {}),
                "create_time": str(m.creation_context.created_at) if m.creation_context else None,
            }
            for m in self.client.models.list(name=name)
        ]


class AzureMLEndpointDeployment:
    name = "azure_ml_endpoint"

    def __init__(
        self,
        registry: AzureMLRegistry | None = None,
    ) -> None:
        self.registry = registry or AzureMLRegistry()

    def deploy(self, model_ref: str, *, environment: str, traffic_pct: int = 100) -> str:
        azureml = _import_azureml()
        endpoint_name = f"puffin-{environment}"
        endpoint = azureml["ManagedOnlineEndpoint"](
            name=endpoint_name,
            auth_mode="key",
        )
        self.registry.client.online_endpoints.begin_create_or_update(endpoint).result()

        # model_ref expected as "azureml:name:version"
        deployment = azureml["ManagedOnlineDeployment"](
            name="default",
            endpoint_name=endpoint_name,
            model=model_ref,
            instance_type=os.environ.get("PUFFIN_AZUREML_INSTANCE_TYPE", "Standard_DS3_v2"),
            instance_count=1,
        )
        self.registry.client.online_deployments.begin_create_or_update(deployment).result()
        return endpoint_name

    def rollback(self, environment: str) -> str:
        log.warning("Azure ML rollback requires UpdateOnlineDeployment with previous version")
        return f"azureml-endpoint://puffin-{environment}"

    def get_endpoint_url(self, environment: str) -> str:
        ep = self.registry.client.online_endpoints.get(name=f"puffin-{environment}")
        return ep.scoring_uri
