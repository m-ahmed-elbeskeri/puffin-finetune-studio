"""Task-quality evaluation.

Reads `eval_sets.golden` (JSONL of {messages, criteria} or {prompt, criteria}),
generates a response per record, applies the rubric, and writes:
    metrics["task_score"]               — fraction of records passing the rubric
    metrics["task_json_validity"]       — fraction of records with valid JSON output
    metrics["task_refusal_rate"]        — fraction of records that were refusals
    metrics["task_records"]             — total number of records evaluated
    metrics["task_per_case"]            — list of per-case results
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from llmops.common.config import load_yaml
from llmops.common.logging import get_logger
from llmops.data.io_utils import read_jsonl
from llmops.evaluation.judges import is_refusal, is_valid_json, rubric_score
from llmops.evaluation.metrics_store import metrics_path, update_metrics
from llmops.evaluation.runner import build_generator
from llmops.features.schemas import Message, Role

log = get_logger(__name__)


def _to_messages(record: dict[str, Any]) -> list[Message]:
    if "messages" in record:
        return [Message(**m) for m in record["messages"]]
    sys_prompt = record.get("system")
    user = record["prompt"]
    msgs = []
    if sys_prompt:
        msgs.append(Message(role=Role.SYSTEM, content=sys_prompt))
    msgs.append(Message(role=Role.USER, content=user))
    return msgs


def run_task_eval(cfg: dict[str, Any]) -> dict[str, Any]:
    eval_cfg = cfg["eval"]
    dataset_path = cfg["datasets"]["golden"]
    if not Path(dataset_path).exists():
        raise FileNotFoundError(f"golden eval set not found: {dataset_path}")

    generator = build_generator(eval_cfg)
    log.info("running task eval with backend=%s on %s", generator.backend, dataset_path)

    per_case: list[dict[str, Any]] = []
    n = 0
    n_pass = 0
    n_refusal = 0
    json_required = 0
    json_valid_when_required = 0

    max_new_tokens = int(cfg.get("eval", {}).get("max_new_tokens", 256))

    for record in read_jsonl(dataset_path):
        n += 1
        criteria = record.get("criteria", {})
        msgs = _to_messages(record)
        result = generator.generate(msgs, max_new_tokens=max_new_tokens)

        rubric = rubric_score(result.text, criteria)
        if rubric["pass"]:
            n_pass += 1
        if criteria.get("require_json"):
            json_required += 1
            if is_valid_json(result.text):
                json_valid_when_required += 1
        if is_refusal(result.text):
            n_refusal += 1

        per_case.append(
            {
                "id": record.get("id", f"case-{n:03d}"),
                "pass": rubric["pass"],
                "checks": rubric["checks"],
                "latency_ms": result.latency_ms,
                "output_chars": len(result.text),
            }
        )

    if n == 0:
        raise RuntimeError(f"no records found in {dataset_path}")

    # JSON validity is only meaningful when at least one case asked for JSON.
    # If no case requires JSON, report 1.0 so the gate doesn't spuriously fail.
    task_json_validity = (
        round(json_valid_when_required / json_required, 4) if json_required else 1.0
    )

    summary = {
        "task_score": round(n_pass / n, 4),
        "task_json_validity": task_json_validity,
        "task_json_records": json_required,
        "task_refusal_rate": round(n_refusal / n, 4),
        "task_records": n,
        "task_per_case": per_case,
    }
    if cfg.get("baseline", {}).get("task_score") is not None:
        baseline = float(cfg["baseline"]["task_score"])
        summary["task_improvement_over_baseline"] = round(summary["task_score"] - baseline, 4)

    out = update_metrics(metrics_path(cfg), summary)
    log.info(
        "task eval done: score=%.3f json=%.3f refusal=%.3f n=%d",
        summary["task_score"],
        summary["task_json_validity"],
        summary["task_refusal_rate"],
        n,
    )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Task-quality eval.")
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    cfg = load_yaml(args.config)
    run_task_eval(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
