"""Regression eval — known-good golden cases the model must NEVER fail again.

Adding to this set is part of the rollback runbook: every production incident
should add at least one record here so the next training run blocks if it
regresses on it.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from llmops.common.config import load_yaml
from llmops.common.logging import get_logger
from llmops.data.io_utils import read_jsonl
from llmops.evaluation.judges import rubric_score
from llmops.evaluation.metrics_store import metrics_path, update_metrics
from llmops.evaluation.runner import build_generator
from llmops.features.schemas import Message, Role

log = get_logger(__name__)


def _to_messages(record: dict[str, Any]) -> list[Message]:
    if "messages" in record:
        return [Message(**m) for m in record["messages"]]
    sys_prompt = record.get("system", "You are a helpful assistant.")
    return [
        Message(role=Role.SYSTEM, content=sys_prompt),
        Message(role=Role.USER, content=record["prompt"]),
    ]


def run_regression_eval(cfg: dict[str, Any]) -> dict[str, Any]:
    eval_cfg = cfg["eval"]
    dataset_path = cfg["datasets"]["regression"]
    if not Path(dataset_path).exists():
        raise FileNotFoundError(f"regression eval set not found: {dataset_path}")

    generator = build_generator(eval_cfg)
    log.info("running regression eval with backend=%s", generator.backend)

    n = 0
    failures = 0
    per_case: list[dict[str, Any]] = []
    max_new_tokens = int(cfg.get("eval", {}).get("max_new_tokens", 256))

    for record in read_jsonl(dataset_path):
        n += 1
        criteria = record.get("criteria", {})
        msgs = _to_messages(record)
        result = generator.generate(msgs, max_new_tokens=max_new_tokens)
        rubric = rubric_score(result.text, criteria)
        if not rubric["pass"]:
            failures += 1
        per_case.append(
            {
                "id": record.get("id", f"regression-{n:03d}"),
                "incident": record.get("incident"),
                "pass": rubric["pass"],
                "checks": rubric["checks"],
            }
        )

    summary = {
        "regression_records": n,
        "regression_failures": failures,
        "regression_pass_rate": round(1 - failures / n, 4) if n else 1.0,
        "regression_per_case": per_case,
    }
    out = update_metrics(metrics_path(cfg), summary)
    log.info("regression eval done: %d / %d failures", failures, n)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Regression eval.")
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    cfg = load_yaml(args.config)
    run_regression_eval(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
