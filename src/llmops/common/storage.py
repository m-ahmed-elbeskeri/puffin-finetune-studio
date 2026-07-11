"""Storage URI parsing and provider dispatch.

Backends are loaded lazily so that local-only users do not need the
google-cloud-storage / boto3 / azure-storage-blob extras installed.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class StorageBackend(Protocol):
    """Minimal contract every storage backend implements."""

    def upload(self, local_path: str | Path, remote_path: str) -> str: ...
    def download(self, remote_path: str, local_path: str | Path) -> Path: ...
    def exists(self, remote_path: str) -> bool: ...
    def list(self, prefix: str) -> list[str]: ...
    def open_read(self, remote_path: str) -> bytes: ...
    def open_write(self, remote_path: str, data: bytes) -> str: ...


@dataclass(frozen=True)
class StorageURI:
    """Parsed storage URI."""

    scheme: str  # local | gs | s3 | az
    bucket: str  # bucket / container; "" for local
    path: str  # relative path within bucket

    @classmethod
    def parse(cls, uri: str) -> StorageURI:
        if "://" not in uri:
            return cls(scheme="local", bucket="", path=uri)
        scheme, rest = uri.split("://", 1)
        if "/" in rest:
            bucket, path = rest.split("/", 1)
        else:
            bucket, path = rest, ""
        scheme_lower = scheme.lower()
        return cls(scheme=scheme_lower, bucket=bucket, path=path)


def get_storage_backend(uri_or_backend: str | None = None) -> StorageBackend:
    """Resolve a backend from a URI scheme or explicit backend name.

    Accepts:
      gs://bucket/path  → GCSStorage
      s3://bucket/path  → S3Storage
      az://container/p  → AzureBlobStorage
      anything else     → LocalStorage rooted at PUFFIN_ARTIFACT_ROOT
    """
    spec = uri_or_backend or os.environ.get("PUFFIN_STORAGE_BACKEND", "local")
    spec_lower = spec.lower()

    if spec_lower.startswith("gs://") or spec_lower in {"gcs", "gs"}:
        from llmops.providers.gcp import GCSStorage

        return GCSStorage()
    if spec_lower.startswith("s3://") or spec_lower in {"s3", "aws"}:
        from llmops.providers.aws import S3Storage

        return S3Storage()
    if spec_lower.startswith("az://") or spec_lower in {"azure_blob", "az"}:
        from llmops.providers.azure import AzureBlobStorage

        return AzureBlobStorage()

    from llmops.providers.local import LocalStorage

    root = os.environ.get("PUFFIN_ARTIFACT_ROOT", "./artifacts")
    return LocalStorage(root=root)
