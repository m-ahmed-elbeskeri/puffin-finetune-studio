"""Lineage helpers: git SHA, config hash, package versions, run identity."""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import platform
import shutil
import socket
import subprocess
from datetime import UTC, datetime
from typing import Any


def git_sha(short: bool = True) -> str | None:
    """Return the current git SHA, or None if not in a git repo / git missing."""
    if shutil.which("git") is None:
        return None
    args = ["git", "rev-parse"]
    if short:
        args.append("--short")
    args.append("HEAD")
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=5, check=False)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


def git_dirty() -> bool | None:
    """True if the working tree has uncommitted changes; None if no git."""
    if shutil.which("git") is None:
        return None
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if out.returncode != 0:
        return None
    return bool(out.stdout.strip())


def hash_dict(d: dict[str, Any]) -> str:
    """Stable SHA256 hex digest of a dict (sorted keys)."""
    return hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode("utf-8")).hexdigest()


_TRACKED_PACKAGES = (
    "transformers",
    "trl",
    "peft",
    "torch",
    "datasets",
    "mlflow",
    "vllm",
    "accelerate",
    "fastapi",
)


def package_versions() -> dict[str, str]:
    """Best-effort snapshot of installed versions of known dependencies."""
    versions: dict[str, str] = {}
    for pkg in _TRACKED_PACKAGES:
        try:
            mod = __import__(pkg)
            versions[pkg] = getattr(mod, "__version__", "unknown")
        except ImportError:
            versions[pkg] = "not-installed"
    return versions


def run_identity() -> dict[str, Any]:
    """Build a lineage record describing where/when/by-whom a run happened."""
    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "host": socket.gethostname(),
        "user": getpass.getuser(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "git_sha": git_sha(short=False),
        "git_dirty": git_dirty(),
        "env": {
            k: v
            for k, v in os.environ.items()
            if k.startswith("PUFFIN_") or k in {"MLFLOW_TRACKING_URI", "MLFLOW_EXPERIMENT_NAME"}
        },
        "packages": package_versions(),
    }
