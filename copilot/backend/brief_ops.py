"""Project brief: a small, persistent design doc for the project.

Captures the intent behind the fine-tune (goal, audience, desired behavior,
data, success criteria, constraints) in configs/project_brief.yaml so every
page and the AI assistant can reference the same source of truth.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

# Field key -> human label. Order is the display order.
BRIEF_FIELDS: dict[str, str] = {
    "title": "Project",
    "goal": "Goal",
    "audience": "Who it's for",
    "desired_behavior": "Desired behavior",
    "data": "Data",
    "success": "Success criteria",
    "constraints": "Constraints & non-goals",
}


def _path(repo_root: Path) -> Path:
    return Path(repo_root) / "configs" / "project_brief.yaml"


def read_brief(repo_root: Path) -> dict[str, Any]:
    import yaml

    p = _path(repo_root)
    data: dict[str, Any] = {}
    if p.exists():
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            data = {}
    fields = {k: str(data.get(k, "") or "") for k in BRIEF_FIELDS}
    return {
        "kind": "project_brief",
        "fields": fields,
        "labels": BRIEF_FIELDS,
        "present": any(v.strip() for v in fields.values()),
    }


def write_brief(repo_root: Path, brief: dict[str, Any]) -> dict[str, Any]:
    import yaml

    clean = {k: str((brief or {}).get(k, "") or "").strip() for k in BRIEF_FIELDS}
    p = _path(repo_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    header = ("# Project brief — the intent behind this fine-tune.\n"
              "# Edited from the Overview page; read by the AI assistant.\n")
    p.write_text(header + yaml.safe_dump(clean, sort_keys=False, allow_unicode=True),
                 encoding="utf-8")
    return read_brief(repo_root)


def brief_summary(repo_root: Path) -> str:
    """Compact plain-text brief for injecting into the AI's context. Empty if
    nothing has been filled in."""
    b = read_brief(repo_root)
    if not b["present"]:
        return ""
    lines = ["Project brief (the goal and constraints for this fine-tune):"]
    for key, label in BRIEF_FIELDS.items():
        val = b["fields"].get(key, "").strip()
        if val:
            lines.append(f"- {label}: {val}")
    return "\n".join(lines)
