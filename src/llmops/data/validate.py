"""Validate the interim dataset against JSON Schema and Pydantic.

Fails fast with a clear, line-pinned error so bad data never reaches training.
Also enforces dataset-level checks: forbidden licenses, max length, leakage.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import jsonschema
from pydantic import ValidationError

from llmops.common.config import load_yaml
from llmops.common.errors import DataValidationError
from llmops.common.logging import get_logger
from llmops.data.io_utils import read_jsonl
from llmops.features.schemas import SFTExample

log = get_logger(__name__)


def _load_schema(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as f:
        return json.load(f)


def validate(cfg: dict[str, Any]) -> dict[str, int]:
    """Validate `paths.interim`. Returns counts. Raises DataValidationError on failure."""
    interim = Path(cfg["paths"]["interim"])
    if not interim.exists():
        raise DataValidationError(f"Interim file not found: {interim} (run ingest first)")

    contracts_dir = Path(cfg.get("contracts_dir", "data_contracts"))
    schema_path = contracts_dir / cfg.get("schema_filename", "sft_schema.json")
    schema = _load_schema(schema_path)
    validator = jsonschema.Draft202012Validator(schema)

    forbidden_licenses = set(cfg.get("forbidden_licenses", []))
    max_total_chars = int(cfg.get("max_total_chars", 200_000))

    n_total = 0
    n_pii = 0
    errors: list[str] = []

    for lineno, record in enumerate(read_jsonl(interim), start=1):
        n_total += 1

        schema_errs = sorted(validator.iter_errors(record), key=lambda e: e.path)
        if schema_errs:
            for err in schema_errs[:3]:
                errors.append(f"line {lineno}: schema: {err.message} at {list(err.path)}")
            continue

        try:
            example = SFTExample.model_validate(record)
        except ValidationError as exc:
            errors.append(f"line {lineno}: pydantic: {exc.errors()[0]['msg']}")
            continue

        if example.license in forbidden_licenses:
            errors.append(f"line {lineno}: forbidden license {example.license!r}")
            continue

        total_chars = sum(len(m.content) for m in example.messages)
        if total_chars > max_total_chars:
            errors.append(f"line {lineno}: total chars {total_chars} > {max_total_chars}")
            continue

        if example.contains_pii:
            n_pii += 1

    if errors:
        head = "\n  ".join(errors[:10])
        more = f"\n  ... ({len(errors) - 10} more)" if len(errors) > 10 else ""
        raise DataValidationError(
            f"{len(errors)} validation error(s) in {interim}:\n  {head}{more}"
        )

    log.info(
        "validation passed: %d records, %d marked contains_pii", n_total, n_pii
    )
    return {"total": n_total, "pii_marked": n_pii, "errors": 0}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate interim dataset.")
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    cfg = load_yaml(args.config)
    try:
        validate(cfg)
    except DataValidationError as exc:
        log.error(str(exc))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
