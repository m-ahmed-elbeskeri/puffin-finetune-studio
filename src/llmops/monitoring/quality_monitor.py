"""Periodic quality monitor — samples production logs and runs an LLM judge.

CLI:
    python -m llmops.monitoring.quality_monitor \
        --requests artifacts/serving/requests.jsonl \
        --sample 50 --output artifacts/monitoring/quality.json
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from llmops.common.logging import get_logger
from llmops.evaluation.judges import is_refusal, is_valid_json
from llmops.evaluation.runner import build_generator

log = get_logger(__name__)


def _sample(records: list[dict[str, Any]], n: int, seed: int = 0) -> list[dict[str, Any]]:
    if len(records) <= n:
        return records
    rng = random.Random(seed)
    return rng.sample(records, n)


def run(
    requests_path: str,
    *,
    output_path: str,
    sample_size: int = 50,
    judge_cfg: dict[str, Any] | None = None,
    seed: int = 0,
) -> dict[str, Any]:
    rec_path = Path(requests_path)
    if not rec_path.exists():
        log.warning("requests log not found at %s; nothing to score", rec_path)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(json.dumps({"sampled": 0}, indent=2), encoding="utf-8")
        return {"sampled": 0}

    records = [
        json.loads(line)
        for line in rec_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and '"output_text"' in line
    ]
    log.info("found %d eligible records (with output_text)", len(records))
    sampled = _sample(records, sample_size, seed=seed)

    refusals = sum(1 for r in sampled if is_refusal(r.get("output_text", "")))
    json_valid = sum(1 for r in sampled if is_valid_json(r.get("output_text", "")))
    output_chars = [len(r.get("output_text", "")) for r in sampled]

    by_model: Counter = Counter()
    for r in sampled:
        by_model[r.get("model_version", "unknown")] += 1

    summary: dict[str, Any] = {
        "sampled": len(sampled),
        "refusal_rate": round(refusals / len(sampled), 4) if sampled else 0.0,
        "json_validity_rate": round(json_valid / len(sampled), 4) if sampled else 0.0,
        "avg_output_chars": (
            round(sum(output_chars) / len(output_chars), 1) if output_chars else 0.0
        ),
        "by_model_version": dict(by_model),
    }

    if judge_cfg and judge_cfg.get("enabled"):
        try:
            generator = build_generator(judge_cfg)
            scores = []
            for rec in sampled:
                from llmops.evaluation.judges import llm_judge_score

                rubric_prompt = judge_cfg.get(
                    "rubric_prompt",
                    "Score the response 0..1 for helpfulness, correctness, and safety. "
                    'Reply with JSON: {"score": <0..1>}.',
                )
                s = llm_judge_score(rec.get("output_text", ""), rubric_prompt, generator)
                scores.append(s["score"])
            if scores:
                summary["judge_mean_score"] = round(sum(scores) / len(scores), 4)
                summary["judge_min_score"] = round(min(scores), 4)
                summary["judge_max_score"] = round(max(scores), 4)
        except Exception as exc:  # pragma: no cover
            log.warning("judge step failed: %s", exc)

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    log.info("wrote quality summary to %s", out)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Quality monitor.")
    parser.add_argument("--requests", default="artifacts/serving/requests.jsonl")
    parser.add_argument("--output", default="artifacts/monitoring/quality.json")
    parser.add_argument("--sample", type=int, default=50)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)
    run(
        args.requests,
        output_path=args.output,
        sample_size=args.sample,
        seed=args.seed,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
