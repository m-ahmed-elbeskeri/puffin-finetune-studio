from __future__ import annotations

from llmops.common.versioning import hash_dict, package_versions, run_identity


def test_hash_dict_stable():
    a = {"x": 1, "y": [2, 3]}
    b = {"y": [2, 3], "x": 1}
    assert hash_dict(a) == hash_dict(b)


def test_package_versions_returns_dict():
    versions = package_versions()
    assert isinstance(versions, dict)
    assert "torch" in versions  # entry exists even if "not-installed"


def test_run_identity_keys():
    ident = run_identity()
    for key in ("timestamp", "host", "user", "platform", "python", "packages"):
        assert key in ident
