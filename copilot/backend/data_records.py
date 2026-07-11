"""Record-level editing for JSONL data files.

View, add, edit, and delete individual records. Every mutation rewrites the
file atomically-ish (write a .bak first) and is jailed to data/ and
eval_sets/. Big files are capped so a stray edit can't rewrite gigabytes.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MAX_RECORDS = 500_000
_ROOTS = ("data", "eval_sets")


class RecordError(ValueError):
    """Bad request (maps to HTTP 400)."""


def _resolve(repo_root: Path, rel: str, *, must_exist: bool) -> Path:
    if not str(rel).lower().endswith(".jsonl"):
        raise RecordError(f"{rel!r}: only .jsonl files can be edited")
    p = (Path(repo_root) / rel).resolve()
    allowed = [str((Path(repo_root) / r).resolve()) for r in _ROOTS]
    if not any(str(p).startswith(a) for a in allowed):
        raise RecordError(f"{rel!r} is outside the editable folders (data/, eval_sets/)")
    if must_exist and not p.exists():
        raise FileNotFoundError(rel)
    return p


def _read_all_lines(path: Path) -> list[str]:
    """Non-empty lines, preserving order. Caps to MAX_RECORDS."""
    lines: list[str] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            s = line.strip()
            if not s:
                continue
            lines.append(s)
            if len(lines) > MAX_RECORDS:
                raise RecordError(
                    f"file has more than {MAX_RECORDS:,} records; edit it with a "
                    "transform script instead")
    return lines


def _write_lines(path: Path, lines: list[str]) -> None:
    backup = path.with_suffix(".jsonl.bak")
    if path.exists():
        backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(lines)
    path.write_text(body + "\n" if body else "", encoding="utf-8")


def read_records(
    repo_root: Path, rel: str, *, offset: int = 0, limit: int = 25,
) -> dict[str, Any]:
    """A window of records. Invalid JSON lines are returned flagged, not hidden,
    so the user can find and fix them."""
    path = _resolve(repo_root, rel, must_exist=True)
    offset = max(0, offset)
    limit = max(1, min(200, limit))
    lines = _read_all_lines(path)
    total = len(lines)
    window = lines[offset:offset + limit]
    records: list[dict[str, Any]] = []
    for i, raw in enumerate(window):
        idx = offset + i
        try:
            records.append({"index": idx, "valid": True, "data": json.loads(raw)})
        except json.JSONDecodeError as exc:
            records.append({
                "index": idx, "valid": False, "raw": raw[:2000],
                "error": f"line {idx + 1}: {exc.msg}",
            })
    return {
        "kind": "record_page",
        "path": rel,
        "total": total,
        "offset": offset,
        "limit": limit,
        "records": records,
    }


def _validate_obj(record: Any) -> str:
    if not isinstance(record, dict):
        raise RecordError("a record must be a JSON object")
    try:
        return json.dumps(record, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise RecordError(f"record is not JSON-serializable: {exc}") from exc


def append_record(repo_root: Path, rel: str, record: Any) -> dict[str, Any]:
    path = _resolve(repo_root, rel, must_exist=False)
    encoded = _validate_obj(record)
    lines = _read_all_lines(path) if path.exists() else []
    lines.append(encoded)
    _write_lines(path, lines)
    return {"ok": True, "total": len(lines), "index": len(lines) - 1}


def update_record(repo_root: Path, rel: str, index: int, record: Any) -> dict[str, Any]:
    path = _resolve(repo_root, rel, must_exist=True)
    encoded = _validate_obj(record)
    lines = _read_all_lines(path)
    if index < 0 or index >= len(lines):
        raise RecordError(f"record {index} is out of range (0..{len(lines) - 1})")
    lines[index] = encoded
    _write_lines(path, lines)
    return {"ok": True, "total": len(lines), "index": index}


def delete_record(repo_root: Path, rel: str, index: int) -> dict[str, Any]:
    path = _resolve(repo_root, rel, must_exist=True)
    lines = _read_all_lines(path)
    if index < 0 or index >= len(lines):
        raise RecordError(f"record {index} is out of range (0..{len(lines) - 1})")
    lines.pop(index)
    _write_lines(path, lines)
    return {"ok": True, "total": len(lines)}
