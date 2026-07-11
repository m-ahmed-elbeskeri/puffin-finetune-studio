"""Drift monitor — compare prompt distributions in prod vs. training.

Two modes:

1. Length / structural drift (no extra dependencies):
   - prompt-length distribution KS-style stat
   - language-distribution proxy (ASCII vs non-ASCII ratio)
   - role distribution

2. Embedding drift (requires sentence-transformers):
   - mean cosine distance between sampled prod embeddings and a fixed
     reference set drawn from the training data.

Outputs `artifacts/monitoring/drift.json`.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import sys
from pathlib import Path
from typing import Any

from llmops.common.logging import get_logger
from llmops.data.io_utils import read_jsonl

log = get_logger(__name__)


def _extract_prompt(record: dict[str, Any]) -> str:
    if "input_messages" in record:
        users = [m.get("content", "") for m in record["input_messages"] if m.get("role") == "user"]
        return users[-1] if users else ""
    if "messages" in record:
        users = [m.get("content", "") for m in record["messages"] if m.get("role") == "user"]
        return users[-1] if users else ""
    return record.get("prompt", "")


def _ascii_ratio(s: str) -> float:
    if not s:
        return 1.0
    return sum(1 for c in s if ord(c) < 128) / len(s)


def _ks_two_sample(a: list[float], b: list[float]) -> float:
    """Two-sample KS D statistic."""
    if not a or not b:
        return 0.0
    a_sorted = sorted(a)
    b_sorted = sorted(b)
    all_vals = sorted(set(a_sorted + b_sorted))
    na = len(a_sorted)
    nb = len(b_sorted)
    d = 0.0
    for v in all_vals:
        fa = sum(1 for x in a_sorted if x <= v) / na
        fb = sum(1 for x in b_sorted if x <= v) / nb
        d = max(d, abs(fa - fb))
    return d


def _length_stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"count": 0, "mean": 0.0, "median": 0.0, "p95": 0.0}
    return {
        "count": len(values),
        "mean": round(statistics.fmean(values), 2),
        "median": round(statistics.median(values), 2),
        "p95": round(
            statistics.quantiles(values, n=20)[-1] if len(values) >= 20 else max(values), 2
        ),
    }


def _embedding_drift(
    prod_prompts: list[str],
    ref_prompts: list[str],
    *,
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    sample: int = 200,
    seed: int = 0,
) -> dict[str, Any]:
    try:
        import numpy as np
        from sentence_transformers import SentenceTransformer  # type: ignore
    except ImportError:
        log.warning("sentence-transformers not installed; skipping embedding drift")
        return {"enabled": False}

    rng = random.Random(seed)
    if len(prod_prompts) > sample:
        prod_prompts = rng.sample(prod_prompts, sample)
    if len(ref_prompts) > sample:
        ref_prompts = rng.sample(ref_prompts, sample)
    if not prod_prompts or not ref_prompts:
        return {"enabled": True, "samples": 0}

    model = SentenceTransformer(model_name)
    e_prod = model.encode(prod_prompts, convert_to_numpy=True, show_progress_bar=False)
    e_ref = model.encode(ref_prompts, convert_to_numpy=True, show_progress_bar=False)

    e_prod = e_prod / (np.linalg.norm(e_prod, axis=1, keepdims=True) + 1e-12)
    e_ref = e_ref / (np.linalg.norm(e_ref, axis=1, keepdims=True) + 1e-12)

    centroid_ref = e_ref.mean(axis=0)
    cos_to_ref = e_prod @ centroid_ref
    distances = 1.0 - cos_to_ref

    return {
        "enabled": True,
        "samples_prod": int(e_prod.shape[0]),
        "samples_ref": int(e_ref.shape[0]),
        "mean_distance_to_ref_centroid": round(float(distances.mean()), 4),
        "p95_distance": round(float(sorted(distances)[int(0.95 * len(distances))]), 4),
        "model": model_name,
    }


def run(
    *,
    prod_path: str,
    train_path: str,
    output_path: str,
    sample: int = 200,
    seed: int = 0,
    enable_embedding: bool = False,
) -> dict[str, Any]:
    prod_prompts = []
    if Path(prod_path).exists():
        for r in read_jsonl(prod_path):
            p = _extract_prompt(r)
            if p:
                prod_prompts.append(p)
    train_prompts = []
    if Path(train_path).exists():
        for r in read_jsonl(train_path):
            p = _extract_prompt(r)
            if p:
                train_prompts.append(p)

    prod_lens = [len(p) for p in prod_prompts]
    train_lens = [len(p) for p in train_prompts]
    ks = _ks_two_sample(prod_lens, train_lens)

    summary: dict[str, Any] = {
        "prod_prompts": len(prod_prompts),
        "train_prompts": len(train_prompts),
        "prod_length_stats": _length_stats(prod_lens),
        "train_length_stats": _length_stats(train_lens),
        "length_ks_statistic": round(ks, 4),
        "ascii_ratio_prod": (
            round(statistics.fmean([_ascii_ratio(p) for p in prod_prompts]), 4)
            if prod_prompts
            else None
        ),
        "ascii_ratio_train": (
            round(statistics.fmean([_ascii_ratio(p) for p in train_prompts]), 4)
            if train_prompts
            else None
        ),
        "drift_warning": ks > 0.2,
    }

    if enable_embedding:
        summary["embedding_drift"] = _embedding_drift(
            prod_prompts, train_prompts, sample=sample, seed=seed
        )

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    log.info("drift summary written to %s (KS=%.3f)", out, ks)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Drift monitor.")
    parser.add_argument("--prod", default="artifacts/serving/requests.jsonl")
    parser.add_argument("--train", default="data/processed/train.jsonl")
    parser.add_argument("--output", default="artifacts/monitoring/drift.json")
    parser.add_argument("--sample", type=int, default=200)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--embedding", action="store_true")
    args = parser.parse_args(argv)
    run(
        prod_path=args.prod,
        train_path=args.train,
        output_path=args.output,
        sample=args.sample,
        seed=args.seed,
        enable_embedding=args.embedding,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
