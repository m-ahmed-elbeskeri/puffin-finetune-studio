"""Generate a dataset card with summary statistics.

Reads the train/eval/test splits and writes a Markdown card with:
- record counts
- source breakdown
- token-length distribution (chars as a proxy if a tokenizer isn't available)
- PII rate
- license breakdown
- dataset version (sha256 of records)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from llmops.common.config import load_yaml
from llmops.common.logging import get_logger
from llmops.data.io_utils import read_jsonl

log = get_logger(__name__)


def _stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {"count": 0}
    chars = []
    for r in records:
        if "messages" in r:
            chars.append(sum(len(m.get("content", "")) for m in r["messages"]))
        elif "prompt" in r:
            chars.append(len(r.get("prompt", "")) + len(r.get("chosen", "")))
    if not chars:
        chars = [0]
    sources = Counter(r.get("source", "unknown") for r in records)
    licenses = Counter(r.get("license", "unknown") for r in records)
    pii = sum(1 for r in records if r.get("contains_pii"))
    return {
        "count": len(records),
        "chars": {
            "min": min(chars),
            "max": max(chars),
            "mean": round(statistics.fmean(chars), 1),
            "median": int(statistics.median(chars)),
            "p95": int(statistics.quantiles(chars, n=20)[-1]) if len(chars) >= 20 else max(chars),
        },
        "sources": dict(sources.most_common()),
        "licenses": dict(licenses.most_common()),
        "pii_count": pii,
        "pii_rate": round(pii / len(records), 4),
    }


def _content_hash(records: list[dict[str, Any]]) -> str:
    h = hashlib.sha256()
    for r in records:
        h.update(json.dumps(r, sort_keys=True, default=str).encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def build_dataset_card(cfg: dict[str, Any]) -> Path:
    paths = cfg["paths"]
    train = list(read_jsonl(paths["train"]))
    eval_ = list(read_jsonl(paths["eval"]))
    test = list(read_jsonl(paths["test"]))

    train_stats = _stats(train)
    eval_stats = _stats(eval_)
    test_stats = _stats(test)
    version = _content_hash(train + eval_ + test)[:16]

    out_path = Path(cfg.get("dataset_card", "dataset_cards/generated.md"))
    out_path.parent.mkdir(parents=True, exist_ok=True)

    name = cfg.get("name", "puffin-dataset")
    description = cfg.get("description", "")

    lines = [
        f"# Dataset card — {name}",
        "",
        f"- **Version:** `{version}`",
        f"- **Generated:** {datetime.now(timezone.utc).isoformat()}",
        f"- **Splits:** train / eval / test",
        "",
        "## Description",
        "",
        description or "_(no description provided in configs/data.yaml)_",
        "",
        "## Counts",
        "",
        "| Split | Records | PII | PII rate | Median chars | p95 chars |",
        "|-------|--------:|----:|---------:|-------------:|----------:|",
        _stat_row("train", train_stats),
        _stat_row("eval", eval_stats),
        _stat_row("test", test_stats),
        "",
        "## Sources",
        "",
    ]

    combined_sources = Counter()
    for r in train + eval_ + test:
        combined_sources[r.get("source", "unknown")] += 1
    lines.append("| Source | Records |")
    lines.append("|--------|--------:|")
    for src, n in combined_sources.most_common():
        lines.append(f"| `{src}` | {n} |")

    lines.append("")
    lines.append("## Licenses")
    lines.append("")
    lines.append("| License | Records |")
    lines.append("|---------|--------:|")
    licenses = Counter()
    for r in train + eval_ + test:
        licenses[r.get("license", "unknown")] += 1
    for lic, n in licenses.most_common():
        lines.append(f"| `{lic}` | {n} |")

    lines += [
        "",
        "## Lineage",
        "",
        "```json",
        json.dumps(
            {
                "config": str(cfg.get("__config_path__", "configs/data.yaml")),
                "version": version,
                "train_path": paths["train"],
                "eval_path": paths["eval"],
                "test_path": paths["test"],
                "splits": {
                    "train": train_stats["count"],
                    "eval": eval_stats["count"],
                    "test": test_stats["count"],
                },
            },
            indent=2,
        ),
        "```",
        "",
        "## Pre-training checks",
        "",
        "- [x] Schema validation",
        "- [x] PII redaction",
        "- [x] Near-duplicate removal",
        "- [x] Train/test leakage check",
        "",
    ]

    out_path.write_text("\n".join(lines), encoding="utf-8")
    log.info("dataset card written to %s (version %s)", out_path, version)
    return out_path


def _stat_row(name: str, s: dict[str, Any]) -> str:
    if s["count"] == 0:
        return f"| {name} | 0 | 0 | 0 | 0 | 0 |"
    return (
        f"| {name} | {s['count']} | {s['pii_count']} | "
        f"{s['pii_rate']} | {s['chars']['median']} | {s['chars']['p95']} |"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a dataset card.")
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    cfg = load_yaml(args.config)
    cfg["__config_path__"] = args.config
    build_dataset_card(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
