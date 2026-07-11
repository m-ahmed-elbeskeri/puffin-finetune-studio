"""Safety evaluation aligned to OWASP-LLM categories.

Each record carries a `severity` (critical | high | medium | low) and a
`criteria` block that the rubric judge checks. Common categories shipped:

- prompt_injection
- jailbreak
- pii_leakage
- toxicity
- training_data_memorization
- unsafe_tool_use
- overclaim_medical_legal_financial

Counts failures per severity and writes:
    metrics["safety_failures_critical"]
    metrics["safety_failures_high"]
    metrics["safety_failures_medium"]
    metrics["safety_failures_low"]
    metrics["safety_per_case"]
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
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


_VALID_SEVERITIES = {"critical", "high", "medium", "low"}


def _to_messages(record: dict[str, Any]) -> list[Message]:
    if "messages" in record:
        return [Message(**m) for m in record["messages"]]
    sys_prompt = record.get("system", "You are a helpful, harmless assistant.")
    return [
        Message(role=Role.SYSTEM, content=sys_prompt),
        Message(role=Role.USER, content=record["prompt"]),
    ]


def run_safety_eval(cfg: dict[str, Any]) -> dict[str, Any]:
    eval_cfg = cfg["eval"]
    dataset_path = cfg["datasets"]["safety"]
    if not Path(dataset_path).exists():
        raise FileNotFoundError(f"safety eval set not found: {dataset_path}")

    generator = build_generator(eval_cfg)
    log.info("running safety eval with backend=%s", generator.backend)

    failures_by_severity: dict[str, int] = defaultdict(int)
    by_category: dict[str, dict[str, int]] = defaultdict(lambda: {"pass": 0, "fail": 0})
    per_case: list[dict[str, Any]] = []
    n = 0

    for record in read_jsonl(dataset_path):
        n += 1
        severity = record.get("severity", "medium").lower()
        if severity not in _VALID_SEVERITIES:
            severity = "medium"
        category = record.get("category", "uncategorized")
        criteria = record.get("criteria", {})

        msgs = _to_messages(record)
        result = generator.generate(msgs, max_new_tokens=int(cfg.get("eval", {}).get("max_new_tokens", 256)))
        rubric = rubric_score(result.text, criteria)

        if not rubric["pass"]:
            failures_by_severity[severity] += 1
            by_category[category]["fail"] += 1
        else:
            by_category[category]["pass"] += 1

        per_case.append(
            {
                "id": record.get("id", f"safety-{n:03d}"),
                "category": category,
                "severity": severity,
                "pass": rubric["pass"],
                "checks": rubric["checks"],
            }
        )

    summary = {
        f"safety_failures_{sev}": failures_by_severity.get(sev, 0)
        for sev in _VALID_SEVERITIES
    }
    summary.update(
        {
            "safety_records": n,
            "safety_pass_rate": round(
                1 - sum(failures_by_severity.values()) / n if n else 1.0, 4
            ),
            "safety_per_case": per_case,
            "safety_by_category": dict(by_category),
        }
    )

    out = update_metrics(metrics_path(cfg), summary)
    log.info(
        "safety eval done: failures critical=%d high=%d medium=%d low=%d (n=%d)",
        summary["safety_failures_critical"],
        summary["safety_failures_high"],
        summary["safety_failures_medium"],
        summary["safety_failures_low"],
        n,
    )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Safety eval.")
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    cfg = load_yaml(args.config)
    run_safety_eval(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
