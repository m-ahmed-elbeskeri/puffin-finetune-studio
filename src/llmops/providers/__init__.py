"""Provider adapters: local, GCP, AWS, Azure, Kubernetes.

All providers implement the contracts defined in `llmops.providers.base`.
Cloud SDKs are imported lazily inside method bodies — importing this package
does NOT require boto3 / google-cloud-* / azure-* / kubernetes to be installed.
"""

from llmops.providers.base import (
    DeploymentBackend,
    ModelRegistry,
    PipelineBackend,
    StorageBackend,
)

__all__ = ["DeploymentBackend", "ModelRegistry", "PipelineBackend", "StorageBackend"]
