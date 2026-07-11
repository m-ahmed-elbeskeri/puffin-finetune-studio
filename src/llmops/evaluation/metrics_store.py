"""Shared metrics file used by all eval modules and read by the gate.

Each eval module appends to a single JSON file (atomic write) so the gate
can read one canonical artifact regardless of execution order.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def metrics_path(cfg: dict[str, Any]) -> Path:
    return Path(cfg.get("output", {}).get("metrics_path", "artifacts/eval/metrics.json"))


def load_metrics(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def update_metrics(path: str | Path, updates: dict[str, Any]) -> dict[str, Any]:
    """Atomic merge-and-write."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    current = load_metrics(p)
    current.update(updates)

    fd, tmp = tempfile.mkstemp(prefix=".metrics-", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2, default=str)
        os.replace(tmp, p)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise
    return current
