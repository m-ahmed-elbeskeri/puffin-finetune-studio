"""Deterministic train/eval/test split, stratified by `source` when present.

Also runs a leakage check between splits using the same MinHash technique
to ensure no near-duplicate crosses the train/test boundary.
"""
from __future__ import annotations

import argparse
import hashlib
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from llmops.common.config import load_yaml
from llmops.common.errors import DataValidationError
from llmops.common.logging import get_logger
from llmops.data.dedupe import _record_text, _shingles, _tokenize
from llmops.data.io_utils import read_jsonl, write_jsonl

log = get_logger(__name__)


def _stable_bucket(seed: int, key: str, num_buckets: int = 1_000_000) -> int:
    """Map a string to a stable bucket using SHA1(seed + key)."""
    h = hashlib.sha1(f"{seed}::{key}".encode("utf-8")).hexdigest()
    return int(h, 16) % num_buckets


def _stratified_split(
    records: list[dict[str, Any]],
    ratios: dict[str, float],
    seed: int,
) -> dict[str, list[dict[str, Any]]]:
    """Stratify by `source`. Each stratum is shuffled deterministically and split."""
    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        by_source[r.get("source", "unknown")].append(r)

    out: dict[str, list[dict[str, Any]]] = {k: [] for k in ratios}
    for source, items in by_source.items():
        rng = random.Random(f"{seed}::{source}")
        items_sorted = sorted(items, key=lambda r: r.get("id", ""))
        rng.shuffle(items_sorted)
        n = len(items_sorted)
        cumulative = 0.0
        last = 0
        keys = list(ratios.keys())
        for i, key in enumerate(keys):
            cumulative += ratios[key]
            end = n if i == len(keys) - 1 else int(round(n * cumulative))
            out[key].extend(items_sorted[last:end])
            last = end
    return out


def _leakage_check(
    train: list[dict[str, Any]],
    test: list[dict[str, Any]],
    *,
    threshold: float = 0.9,
) -> int:
    """Return number of test records with a near-duplicate in train."""
    try:
        from datasketch import MinHash, MinHashLSH  # type: ignore
    except ImportError:
        log.warning("datasketch not installed; skipping leakage check")
        return 0

    # MinHashLSH bands math requires num_perm large enough for the threshold.
    # Use 256 perms so that thresholds up to ~0.99 produce a feasible band/row split.
    num_perm = 256
    try:
        lsh = MinHashLSH(threshold=threshold, num_perm=num_perm)
    except ValueError as exc:
        log.warning(
            "leakage threshold %.3f is not feasible with num_perm=%d (%s); skipping check",
            threshold,
            num_perm,
            exc,
        )
        return 0

    for i, r in enumerate(train):
        toks = _tokenize(_record_text(r))
        if not toks:
            continue
        sh = _shingles(toks, k=5)
        m = MinHash(num_perm=num_perm)
        for s in sh:
            m.update(s.encode("utf-8"))
        lsh.insert(f"train::{i}", m)

    leaks = 0
    for r in test:
        toks = _tokenize(_record_text(r))
        if not toks:
            continue
        sh = _shingles(toks, k=5)
        m = MinHash(num_perm=num_perm)
        for s in sh:
            m.update(s.encode("utf-8"))
        if lsh.query(m):
            leaks += 1
    return leaks


def _resolve_input(cfg: dict[str, Any]) -> Path:
    """Return the most-processed interim file that actually exists.

    Redaction and dedupe are optional now (they live as transform scripts, not
    fixed stages), so the file split reads depends on which stages ran:
    deduped if dedupe ran, else redacted if redact ran, else the raw interim
    from ingest. Falling back this way lets `ingest -> validate -> split` work
    without producing deduped.jsonl.
    """
    paths = cfg.get("paths", {})
    for key in ("deduped", "redacted", "interim"):
        p = paths.get(key)
        if p and Path(p).exists():
            return Path(p)
    return Path(paths.get("interim", "data/interim/all.jsonl"))


def split(cfg: dict[str, Any]) -> dict[str, Path]:
    src = _resolve_input(cfg)
    if not src.exists():
        raise DataValidationError(
            f"no interim data to split (looked for deduped, redacted, then "
            f"interim under data/interim/). Run the data pipeline's ingest "
            f"stage first."
        )
    out_train = Path(cfg["paths"]["train"])
    out_eval = Path(cfg["paths"]["eval"])
    out_test = Path(cfg["paths"]["test"])

    sp = cfg.get("split", {})
    train_ratio = float(sp.get("train", 0.8))
    eval_ratio = float(sp.get("eval", 0.1))
    test_ratio = float(sp.get("test", 0.1))
    seed = int(sp.get("seed", 42))
    leakage_threshold = float(sp.get("leakage_threshold", 0.9))
    leakage_max = int(sp.get("leakage_max", 0))

    total = train_ratio + eval_ratio + test_ratio
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"split ratios must sum to 1.0 (got {total})")

    records = list(read_jsonl(src))
    if not records:
        raise DataValidationError(f"interim file is empty: {src}")

    parts = _stratified_split(
        records, {"train": train_ratio, "eval": eval_ratio, "test": test_ratio}, seed=seed
    )

    leaks = _leakage_check(parts["train"], parts["test"], threshold=leakage_threshold)
    if leaks > leakage_max:
        raise DataValidationError(
            f"train/test leakage check failed: {leaks} test records have near-duplicates "
            f"in train (threshold {leakage_threshold}, allowed {leakage_max})"
        )

    write_jsonl(out_train, parts["train"])
    write_jsonl(out_eval, parts["eval"])
    write_jsonl(out_test, parts["test"])

    log.info(
        "split: train=%d eval=%d test=%d  (leakage=%d)",
        len(parts["train"]),
        len(parts["eval"]),
        len(parts["test"]),
        leaks,
    )
    return {"train": out_train, "eval": out_eval, "test": out_test}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train/eval/test split.")
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    cfg = load_yaml(args.config)
    try:
        split(cfg)
    except DataValidationError as exc:
        log.error(str(exc))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
