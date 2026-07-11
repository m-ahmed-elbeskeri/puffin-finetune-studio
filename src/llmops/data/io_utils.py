"""Small JSONL helpers used across the data pipeline."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Iterator


def read_jsonl(path: str | Path) -> Iterator[dict[str, Any]]:
    """Yield objects from a JSONL file. Skips blank lines; raises on malformed JSON."""
    path = Path(path)
    with path.open("r", encoding="utf-8") as f:
        for lineno, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{lineno}: invalid JSON ({exc.msg})") from exc
            if not isinstance(obj, dict):
                raise ValueError(f"{path}:{lineno}: expected object, got {type(obj).__name__}")
            yield obj


def write_jsonl(path: str | Path, records: Iterable[dict[str, Any]]) -> int:
    """Write records as JSONL. Returns count written. Creates parent dirs."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False, default=str))
            f.write("\n")
            count += 1
    return count


def count_lines(path: str | Path) -> int:
    """Count non-empty lines in a JSONL file."""
    path = Path(path)
    if not path.exists():
        return 0
    n = 0
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                n += 1
    return n
