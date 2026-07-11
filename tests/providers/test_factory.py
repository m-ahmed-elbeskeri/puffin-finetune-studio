from __future__ import annotations

import pytest

from llmops.common.errors import ConfigError
from llmops.providers.factory import (
    get_deployment,
    get_pipeline_backend,
    get_registry,
    get_storage,
)
from llmops.providers.local import LocalDeployment, LocalRegistry, LocalStorage


def test_factory_local_storage():
    s = get_storage({"storage": {"backend": "local"}})
    assert isinstance(s, LocalStorage)


def test_factory_local_registry():
    r = get_registry({"registry": {"backend": "local"}})
    assert isinstance(r, LocalRegistry)


def test_factory_local_deployment():
    d = get_deployment({"deployment": {"backend": "local"}})
    assert isinstance(d, LocalDeployment)


def test_factory_pipelines_none():
    assert get_pipeline_backend({"pipelines": {"backend": "none"}}) is None


def test_factory_unknown_backend():
    with pytest.raises(ConfigError):
        get_storage({"storage": {"backend": "frobnitz"}})
    with pytest.raises(ConfigError):
        get_registry({"registry": {"backend": "frobnitz"}})
    with pytest.raises(ConfigError):
        get_deployment({"deployment": {"backend": "frobnitz"}})


def test_factory_can_construct_cloud_specs_lazily():
    """Importing the factory and SELECTING a cloud backend must not fail at import.

    Actual cloud SDK calls would fail without credentials, but constructing
    the adapter object must succeed (lazy init).
    """
    # GCS adapter constructs without making RPCs.
    s = get_storage({"storage": {"backend": "gcs", "bucket": "x"}})
    assert s.name == "gcs"
    s = get_storage({"storage": {"backend": "s3", "bucket": "x", "region": "us-east-1"}})
    assert s.name == "s3"
    s = get_storage(
        {
            "storage": {
                "backend": "azure_blob",
                "container": "x",
                "account_url": "https://x.blob.core.windows.net",
            }
        }
    )
    assert s.name == "azure_blob"
