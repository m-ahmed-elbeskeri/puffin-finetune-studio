"""Ingest raw data files (JSONL or JSON arrays) into the canonical interim format.

Reads each source listed in `configs/data.yaml::sources`, normalizes the records,
and writes a single combined JSONL file at `paths.interim`.
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any, Iterator

from llmops.common.config import load_yaml
from llmops.common.logging import get_logger
from llmops.data.io_utils import read_jsonl, write_jsonl

log = get_logger(__name__)


def _read_records(path: str | Path) -> Iterator[dict[str, Any]]:
    """Read either JSONL or a JSON array file."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Source file not found: {path}")

    suffix = path.suffix.lower()
    if suffix in {".jsonl", ".ndjson"}:
        yield from read_jsonl(path)
        return

    if suffix == ".json":
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            for r in data:
                if not isinstance(r, dict):
                    raise ValueError(f"{path}: expected list of objects")
                yield r
        elif isinstance(data, dict):
            yield data
        else:
            raise ValueError(f"{path}: expected list or object, got {type(data).__name__}")
        return

    raise ValueError(f"Unsupported source format: {path.suffix}")


def _normalize(record: dict[str, Any], source: str) -> dict[str, Any]:
    """Normalize a single record into the SFT canonical shape."""
    if "id" not in record:
        record["id"] = str(uuid.uuid4())
    if "source" not in record:
        record["source"] = source

    # Allow lightweight {"prompt": ..., "response": ...} style and convert it
    if "messages" not in record and "prompt" in record and "response" in record:
        system = record.pop("system", None)
        msgs: list[dict[str, str]] = []
        if system:
            msgs.append({"role": "system", "content": str(system)})
        msgs.append({"role": "user", "content": str(record.pop("prompt"))})
        msgs.append({"role": "assistant", "content": str(record.pop("response"))})
        record["messages"] = msgs

    record.setdefault("license", "unknown")
    record.setdefault("contains_pii", False)
    record.setdefault("quality_score", 1.0)
    return record


def _discover_sources(raw_dir: Path = Path("data/raw")) -> list[dict[str, str]]:
    """Zero-config golden path: every *.jsonl dropped in data/raw/ is a
    source named after its file stem. Explicit `sources:` entries in
    configs/data.yaml take precedence when present."""
    return [
        {"name": p.stem, "path": str(p)}
        for p in sorted(raw_dir.glob("*.jsonl"))
    ]


def ingest(cfg: dict[str, Any]) -> Path:
    sources = cfg.get("sources") or []
    if not sources:
        sources = _discover_sources()
        if sources:
            log.info(
                "no sources configured — auto-discovered %d file(s) in data/raw/",
                len(sources),
            )
    if not sources:
        raise ValueError(
            "no data sources: configs/data.yaml `sources:` is empty and "
            "data/raw/ contains no .jsonl files"
        )
    interim_path = Path(cfg["paths"]["interim"])

    total = 0
    skipped = 0

    def _stream() -> Iterator[dict[str, Any]]:
        nonlocal total, skipped
        for src in sources:
            name = src["name"]
            path = src["path"]
            log.info("ingesting source %s from %s", name, path)
            for raw in _read_records(path):
                try:
                    yield _normalize(dict(raw), source=name)
                    total += 1
                except (KeyError, ValueError) as exc:
                    skipped += 1
                    log.warning("skipping malformed record: %s", exc)

    n = write_jsonl(interim_path, _stream())
    log.info("ingest complete: wrote %d records (%d skipped) to %s", n, skipped, interim_path)
    return interim_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest raw data into interim JSONL.")
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    cfg = load_yaml(args.config)
    ingest(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
