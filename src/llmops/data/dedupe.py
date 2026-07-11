"""Near-duplicate removal via MinHash + LSH (datasketch).

Falls back to exact-hash dedup if datasketch isn't installed.

Computes a MinHash signature per record over the concatenated message text,
then uses an LSH index to find pairs above the configured Jaccard threshold.
For each duplicate cluster, keeps the record with the highest quality_score
(ties broken by record id).
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Iterator

from llmops.common.config import load_yaml
from llmops.common.logging import get_logger
from llmops.data.io_utils import read_jsonl, write_jsonl

log = get_logger(__name__)

_TOKEN_RE = re.compile(r"\w+", flags=re.UNICODE)


def _record_text(record: dict[str, Any]) -> str:
    """Build the text used for fingerprinting."""
    if "messages" in record:
        return "\n".join(m.get("content", "") for m in record["messages"]).strip().lower()
    if "prompt" in record and "chosen" in record:
        return f"{record.get('prompt', '')}\n{record.get('chosen', '')}".strip().lower()
    return ""


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text)


def _shingles(tokens: list[str], k: int = 5) -> set[str]:
    if len(tokens) <= k:
        return {" ".join(tokens)} if tokens else set()
    return {" ".join(tokens[i : i + k]) for i in range(len(tokens) - k + 1)}


def _exact_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _quality(record: dict[str, Any]) -> float:
    return float(record.get("quality_score", 1.0))


def _select_keepers_minhash(
    records: list[dict[str, Any]],
    *,
    threshold: float,
    num_perm: int,
    shingle_k: int,
) -> set[int]:
    """Return the set of indices to keep, using MinHash + LSH."""
    try:
        from datasketch import MinHash, MinHashLSH  # type: ignore
    except ImportError:
        log.warning("datasketch not installed; falling back to exact hash dedup")
        return _select_keepers_exact(records)

    lsh = MinHashLSH(threshold=threshold, num_perm=num_perm)
    sigs: dict[int, Any] = {}
    for i, rec in enumerate(records):
        tokens = _tokenize(_record_text(rec))
        if not tokens:
            sigs[i] = None
            continue
        shingles = _shingles(tokens, k=shingle_k)
        m = MinHash(num_perm=num_perm)
        for s in shingles:
            m.update(s.encode("utf-8"))
        sigs[i] = m
        lsh.insert(str(i), m)

    seen: set[int] = set()
    kept: set[int] = set()
    for i, rec in enumerate(records):
        if i in seen:
            continue
        sig = sigs[i]
        if sig is None:
            kept.add(i)
            seen.add(i)
            continue
        cluster_idx = [int(x) for x in lsh.query(sig)]
        if not cluster_idx:
            cluster_idx = [i]
        cluster_idx = [j for j in cluster_idx if j not in seen]
        if not cluster_idx:
            continue
        best = max(
            cluster_idx,
            key=lambda j: (_quality(records[j]), -j),
        )
        kept.add(best)
        seen.update(cluster_idx)

    return kept


def _select_keepers_exact(records: list[dict[str, Any]]) -> set[int]:
    by_hash: dict[str, int] = {}
    for i, rec in enumerate(records):
        text = _record_text(rec)
        if not text:
            by_hash[f"__empty_{i}"] = i
            continue
        h = _exact_hash(text)
        if h in by_hash:
            existing = by_hash[h]
            if _quality(rec) > _quality(records[existing]):
                by_hash[h] = i
        else:
            by_hash[h] = i
    return set(by_hash.values())


def dedupe(cfg: dict[str, Any]) -> Path:
    # Redact is optional now, so read redacted.jsonl if it was produced,
    # otherwise fall back to the raw interim from ingest.
    paths = cfg.get("paths", {})
    redacted = Path(paths["redacted"])
    src = redacted if redacted.exists() else Path(paths["interim"])
    output = Path(cfg["paths"]["deduped"])
    threshold = float(cfg.get("dedupe", {}).get("jaccard_threshold", 0.85))
    num_perm = int(cfg.get("dedupe", {}).get("num_perm", 128))
    shingle_k = int(cfg.get("dedupe", {}).get("shingle_k", 5))

    records = list(read_jsonl(src))
    n_in = len(records)

    keepers = _select_keepers_minhash(
        records, threshold=threshold, num_perm=num_perm, shingle_k=shingle_k
    )
    kept_records: Iterable[dict[str, Any]] = (records[i] for i in sorted(keepers))
    n_out = write_jsonl(output, kept_records)
    log.info("dedupe: %d → %d records (removed %d)", n_in, n_out, n_in - n_out)
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Remove near-duplicates.")
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    cfg = load_yaml(args.config)
    dedupe(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
