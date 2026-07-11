"""Local provider — filesystem storage + JSON-file model registry.

Useful for laptop development, CI, and offline reproductions.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class LocalStorage:
    name = "local"

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root or os.environ.get("PUFFIN_ARTIFACT_ROOT", "./artifacts"))
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, remote_path: str) -> Path:
        path = Path(remote_path)
        if path.is_absolute():
            return path
        return self.root / remote_path

    def upload(self, local_path: str | Path, remote_path: str) -> str:
        src = Path(local_path)
        dst = self._resolve(remote_path)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
        return str(dst)

    def download(self, remote_path: str, local_path: str | Path) -> Path:
        src = self._resolve(remote_path)
        dst = Path(local_path)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
        return dst

    def exists(self, remote_path: str) -> bool:
        return self._resolve(remote_path).exists()

    def list(self, prefix: str) -> list[str]:
        base = self._resolve(prefix)
        if base.is_file():
            return [str(base.relative_to(self.root))]
        if not base.exists():
            return []
        return [str(p.relative_to(self.root)) for p in base.rglob("*") if p.is_file()]

    def open_read(self, remote_path: str) -> bytes:
        return self._resolve(remote_path).read_bytes()

    def open_write(self, remote_path: str, data: bytes) -> str:
        path = self._resolve(remote_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return str(path)


class LocalRegistry:
    """File-based registry. Stores artifacts and a JSON manifest under `<root>/_registry/`."""

    name = "local"

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root or os.environ.get("PUFFIN_ARTIFACT_ROOT", "./artifacts"))
        self.registry_root = self.root / "_registry"
        self.registry_root.mkdir(parents=True, exist_ok=True)

    def _manifest_path(self, name: str) -> Path:
        return self.registry_root / name / "manifest.json"

    def _read_manifest(self, name: str) -> dict[str, Any]:
        mp = self._manifest_path(name)
        if mp.exists():
            return json.loads(mp.read_text(encoding="utf-8"))
        return {"name": name, "versions": [], "aliases": {}}

    def _write_manifest(self, name: str, manifest: dict[str, Any]) -> None:
        mp = self._manifest_path(name)
        mp.parent.mkdir(parents=True, exist_ok=True)
        mp.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")

    def register_model(
        self,
        model_path: str | Path,
        *,
        name: str,
        version: str | None = None,
        metrics: dict[str, float] | None = None,
        tags: dict[str, str] | None = None,
    ) -> str:
        manifest = self._read_manifest(name)
        next_idx = (
            max(
                (int(v["version"]) for v in manifest["versions"] if v["version"].isdigit()),
                default=0,
            )
            + 1
        )
        version = version or str(next_idx)

        dest = self.registry_root / name / f"v{version}"
        if dest.exists():
            shutil.rmtree(dest)
        src = Path(model_path)
        if src.is_dir():
            shutil.copytree(src, dest)
        else:
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest / src.name)

        manifest["versions"].append(
            {
                "version": version,
                "path": str(dest),
                "registered_at": datetime.now(UTC).isoformat(),
                "metrics": metrics or {},
                "tags": tags or {},
            }
        )
        manifest["aliases"].setdefault("candidate", version)
        self._write_manifest(name, manifest)
        return f"local:{name}/v{version}"

    def promote(self, name: str, version: str, alias: str) -> None:
        manifest = self._read_manifest(name)
        if not any(v["version"] == version for v in manifest["versions"]):
            raise ValueError(f"version {version} of {name} is not registered")
        manifest["aliases"][alias] = version
        self._write_manifest(name, manifest)

    def get_model_uri(self, name: str, alias: str = "production") -> str:
        manifest = self._read_manifest(name)
        version = manifest["aliases"].get(alias)
        if not version:
            raise KeyError(f"alias {alias!r} not set on model {name}")
        return f"local:{name}/v{version}"

    def list_versions(self, name: str) -> list[dict[str, Any]]:
        return self._read_manifest(name)["versions"]


class LocalDeployment:
    """Local 'deployment' — writes a deployment manifest to disk.

    Real deployment is just `make serve`; this class exists so the same code
    path can be exercised against the Protocol.
    """

    name = "local"

    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root or os.environ.get("PUFFIN_ARTIFACT_ROOT", "./artifacts"))
        self.dir = self.root / "_deployments"
        self.dir.mkdir(parents=True, exist_ok=True)

    def deploy(self, model_ref: str, *, environment: str, traffic_pct: int = 100) -> str:
        manifest = {
            "model_ref": model_ref,
            "environment": environment,
            "traffic_pct": traffic_pct,
            "deployed_at": datetime.now(UTC).isoformat(),
        }
        path = self.dir / f"{environment}.json"
        path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return f"local-deployment://{environment}"

    def rollback(self, environment: str) -> str:
        path = self.dir / f"{environment}.json"
        backup = self.dir / f"{environment}.previous.json"
        if backup.exists():
            shutil.copy2(backup, path)
            return f"rolled back local-deployment://{environment}"
        raise FileNotFoundError(f"no previous deployment for {environment}")

    def get_endpoint_url(self, environment: str) -> str:
        host = os.environ.get("PUFFIN_SERVE_HOST", "127.0.0.1")
        port = os.environ.get("PUFFIN_SERVE_PORT", "8080")
        return f"http://{host}:{port}"
