"""Environment doctor: which Python packages the platform needs, what is
installed, and one-click install of the missing pieces.

Training and cloud submission import heavy optional packages (torch, trl,
peft, boto3, ...) that aren't in the base install. When they're missing a run
just dies, so the Train page surfaces readiness here and can install the right
`pip install -e ".[extra]"` group on demand, streaming the output live.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
from pathlib import Path
from typing import Any, AsyncIterator


def _pkg(import_name: str, pip_name: str | None = None) -> dict[str, str]:
    return {"import": import_name, "pip": pip_name or import_name}


# Each group maps to a pip extra (or an explicit package list) and the modules
# that must import for the feature to work.
GROUPS: list[dict[str, Any]] = [
    {
        "id": "train", "label": "Local training", "extra": "train",
        "purpose": "Run SFT / LoRA and DPO fine-tuning on this machine.",
        "packages": [
            _pkg("torch"), _pkg("transformers"), _pkg("trl"), _pkg("peft"),
            _pkg("accelerate"), _pkg("datasets"), _pkg("sentencepiece"),
        ],
    },
    {
        "id": "quantization", "label": "Quantization (QLoRA)", "extra": None,
        "install": ["bitsandbytes"],
        "purpose": "4-bit / 8-bit loading so large models fit on one GPU.",
        "packages": [_pkg("bitsandbytes")],
    },
    {
        "id": "data", "label": "Data pipeline", "extra": "data",
        "purpose": "Dedupe, near-duplicate detection, and dataset stats.",
        "packages": [
            _pkg("datasets"), _pkg("datasketch"),
            _pkg("sklearn", "scikit-learn"), _pkg("pandas"),
        ],
    },
    {
        "id": "eval", "label": "Evaluation", "extra": "eval",
        "purpose": "Task and quality metrics for the promotion gate.",
        "packages": [
            _pkg("evaluate"), _pkg("rouge_score", "rouge-score"),
            _pkg("sentence_transformers", "sentence-transformers"),
        ],
    },
    {
        "id": "aws", "label": "AWS / SageMaker", "extra": "aws",
        "purpose": "Submit cloud training jobs to Amazon SageMaker.",
        "packages": [_pkg("boto3"), _pkg("sagemaker")],
    },
    {
        "id": "gcp", "label": "Google Cloud / Vertex AI", "extra": "gcp",
        "purpose": "Submit cloud training jobs to Vertex AI.",
        "packages": [
            _pkg("google.cloud.storage", "google-cloud-storage"),
            _pkg("google.cloud.aiplatform", "google-cloud-aiplatform"),
        ],
    },
    {
        "id": "azure", "label": "Azure ML", "extra": "azure",
        "purpose": "Submit cloud training jobs to Azure Machine Learning.",
        "packages": [
            _pkg("azure.ai.ml", "azure-ai-ml"),
            _pkg("azure.identity", "azure-identity"),
        ],
    },
    {
        "id": "mlflow", "label": "MLflow tracking", "extra": "mlflow",
        "purpose": "Optional external experiment tracking.",
        "packages": [_pkg("mlflow")],
    },
]

_GROUPS_BY_ID = {g["id"]: g for g in GROUPS}


class EnvironmentError_(ValueError):
    """Bad group id (maps to HTTP 400)."""


def _importable(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError, AttributeError, ModuleNotFoundError):
        return False


def _version(pip_name: str) -> str | None:
    try:
        import importlib.metadata as md
        return md.version(pip_name)
    except Exception:  # noqa: BLE001
        return None


def _platform_root() -> Path | None:
    """Directory holding the platform's pyproject.toml (puffin-finetune-studio),
    found from this module's own location. The training/cloud packages are
    dependencies of THIS package, not of whichever data project is selected,
    so installs must run here — not in the user's project folder."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return None


def _install_command(g: dict[str, Any]) -> str:
    # If we can find the platform's pyproject, use its pinned extra; otherwise
    # fall back to installing the packages by name (works from any directory).
    if g.get("extra") and _platform_root() is not None:
        return f'pip install -e ".[{g["extra"]}]"'
    pkgs = g.get("install") or [p["pip"] for p in g["packages"]]
    return "pip install " + " ".join(pkgs)


def _install_argv(g: dict[str, Any]) -> tuple[list[str], Path]:
    """Return (argv, cwd). Prefer the platform's `-e .[extra]` (respects the
    version pins) run from the platform root; fall back to explicit package
    names when the pyproject can't be located."""
    root = _platform_root()
    pip = [sys.executable, "-m", "pip", "install"]
    if g.get("extra") and root is not None:
        return (pip + ["-e", f".[{g['extra']}]"], root)
    pkgs = g.get("install") or [p["pip"] for p in g["packages"]]
    return (pip + pkgs, root or Path.cwd())


def check_environment() -> dict[str, Any]:
    """Readiness report for every capability group."""
    groups: list[dict[str, Any]] = []
    for g in GROUPS:
        pkgs = []
        for p in g["packages"]:
            ok = _importable(p["import"])
            pkgs.append({
                "import": p["import"], "pip": p["pip"],
                "installed": ok, "version": _version(p["pip"]) if ok else None,
            })
        n_ok = sum(1 for p in pkgs if p["installed"])
        groups.append({
            "id": g["id"], "label": g["label"], "purpose": g["purpose"],
            "packages": pkgs,
            "installed_count": n_ok, "total": len(pkgs),
            "ready": n_ok == len(pkgs),
            "install_command": _install_command(g),
        })
    return {
        "kind": "environment",
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "groups": groups,
    }


async def stream_install(group_id: str) -> AsyncIterator[tuple[str, str]]:
    """Run `pip install` for a group and yield (event, line) tuples.

    Events: "log" per output line, then "done" with the exit code, or "error".
    Only the platform's own declared groups can be installed, so this can't be
    coaxed into installing arbitrary packages. Always runs from the platform
    directory (where pyproject.toml lives), never the selected data project.
    """
    g = _GROUPS_BY_ID.get(group_id)
    if g is None:
        yield ("error", f"unknown environment group: {group_id}")
        return
    argv, cwd = _install_argv(g)
    yield ("log", f"# installing into {sys.executable}")
    yield ("log", f"# from {cwd}")
    yield ("log", "$ " + " ".join(argv[1:]))
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONUTF8": "1"}
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT, env=env,
        )
    except OSError as exc:
        yield ("error", f"could not start pip: {exc}")
        return
    assert proc.stdout is not None
    try:
        async for raw in proc.stdout:
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if line:
                yield ("log", line)
    except asyncio.CancelledError:
        proc.kill()
        raise
    code = await proc.wait()
    yield ("done", str(code))
