"""Build the right provider for the current profile."""

from __future__ import annotations

from typing import Any

from llmops.common.errors import ConfigError
from llmops.providers.base import (
    DeploymentBackend,
    ModelRegistry,
    PipelineBackend,
    StorageBackend,
)


def get_storage(profile: dict[str, Any]) -> StorageBackend:
    backend = profile.get("storage", {}).get("backend", "local")
    cfg = profile.get("storage", {})
    if backend == "local":
        from llmops.providers.local import LocalStorage

        return LocalStorage(root=cfg.get("root"))
    if backend in {"gcs", "gs"}:
        from llmops.providers.gcp import GCSStorage

        return GCSStorage(default_bucket=cfg.get("bucket"))
    if backend in {"s3", "aws"}:
        from llmops.providers.aws import S3Storage

        return S3Storage(default_bucket=cfg.get("bucket"), region=cfg.get("region"))
    if backend in {"azure_blob", "az"}:
        from llmops.providers.azure import AzureBlobStorage

        return AzureBlobStorage(
            account_url=cfg.get("account_url"),
            default_container=cfg.get("container"),
        )
    raise ConfigError(f"unknown storage backend: {backend!r}")


def get_registry(profile: dict[str, Any]) -> ModelRegistry:
    backend = profile.get("registry", {}).get("backend", "local")
    cfg = profile.get("registry", {})
    if backend == "local":
        from llmops.providers.local import LocalRegistry

        return LocalRegistry(root=cfg.get("root"))
    if backend == "vertex_ai":
        from llmops.providers.gcp import VertexAIModelRegistry

        return VertexAIModelRegistry(project=cfg.get("project"), location=cfg.get("location"))
    if backend == "sagemaker":
        from llmops.providers.aws import SageMakerRegistry

        return SageMakerRegistry(region=cfg.get("region"), role_arn=cfg.get("role_arn"))
    if backend == "azure_ml":
        from llmops.providers.azure import AzureMLRegistry

        return AzureMLRegistry(
            subscription_id=cfg.get("subscription_id"),
            resource_group=cfg.get("resource_group"),
            workspace_name=cfg.get("workspace_name"),
        )
    if backend == "mlflow":
        from llmops.providers.mlflow_registry import MLflowRegistry

        return MLflowRegistry(tracking_uri=cfg.get("tracking_uri"))
    raise ConfigError(f"unknown registry backend: {backend!r}")


def get_deployment(profile: dict[str, Any]) -> DeploymentBackend:
    backend = profile.get("deployment", {}).get("backend", "local")
    cfg = profile.get("deployment", {})
    if backend == "local":
        from llmops.providers.local import LocalDeployment

        return LocalDeployment(root=cfg.get("root"))
    if backend == "vertex_endpoint":
        from llmops.providers.gcp import VertexAIEndpointDeployment

        return VertexAIEndpointDeployment(project=cfg.get("project"), location=cfg.get("location"))
    if backend == "sagemaker_endpoint":
        from llmops.providers.aws import SageMakerEndpointDeployment

        return SageMakerEndpointDeployment(region=cfg.get("region"), role_arn=cfg.get("role_arn"))
    if backend == "azure_ml_endpoint":
        from llmops.providers.azure import AzureMLEndpointDeployment

        return AzureMLEndpointDeployment()
    if backend == "kubernetes":
        from llmops.providers.kubernetes import K8sDeployment

        return K8sDeployment(
            namespace=cfg.get("namespace"),
            context=cfg.get("context"),
            serving_image=cfg.get("serving_image"),
        )
    raise ConfigError(f"unknown deployment backend: {backend!r}")


def get_pipeline_backend(profile: dict[str, Any]) -> PipelineBackend | None:
    backend = profile.get("pipelines", {}).get("backend", "none")
    cfg = profile.get("pipelines", {})
    if backend == "none":
        return None
    if backend == "vertex_pipelines":
        from llmops.providers.gcp import VertexAIPipelines

        return VertexAIPipelines(project=cfg.get("project"), location=cfg.get("location"))
    raise ConfigError(f"unknown pipelines backend: {backend!r}")
