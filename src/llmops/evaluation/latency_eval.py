"""Latency / cost eval.

Repeats each prompt N times, computes p50/p95/p99 latency and tokens/sec,
and estimates cost per 1k requests using a simple per-token price map.
"""
from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path
from typing import Any

from llmops.common.config import load_yaml
from llmops.common.logging import get_logger
from llmops.data.io_utils import read_jsonl
from llmops.evaluation.metrics_store import metrics_path, update_metrics
from llmops.evaluation.runner import build_generator
from llmops.features.schemas import Message, Role

log = get_logger(__name__)


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * q
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def _to_messages(record: dict[str, Any]) -> list[Message]:
    if "messages" in record:
        return [Message(**m) for m in record["messages"]]
    return [
        Message(role=Role.SYSTEM, content=record.get("system", "You are a helpful assistant.")),
        Message(role=Role.USER, content=record["prompt"]),
    ]


def run_latency_eval(cfg: dict[str, Any]) -> dict[str, Any]:
    eval_cfg = cfg["eval"]
    dataset_path = cfg["datasets"]["latency"]
    if not Path(dataset_path).exists():
        raise FileNotFoundError(f"latency eval set not found: {dataset_path}")

    repeats = int(cfg.get("latency", {}).get("repeats", 3))
    warmups = int(cfg.get("latency", {}).get("warmups", 1))
    max_new_tokens = int(cfg.get("latency", {}).get("max_new_tokens", 64))
    cost_per_1k_input = float(cfg.get("latency", {}).get("cost_per_1k_input_tokens", 0.0))
    cost_per_1k_output = float(cfg.get("latency", {}).get("cost_per_1k_output_tokens", 0.0))

    generator = build_generator(eval_cfg)

    latencies: list[float] = []
    in_toks = 0
    out_toks = 0
    n = 0

    for record in read_jsonl(dataset_path):
        n += 1
        msgs = _to_messages(record)
        for _ in range(warmups):
            generator.generate(msgs, max_new_tokens=max_new_tokens)
        for _ in range(repeats):
            r = generator.generate(msgs, max_new_tokens=max_new_tokens)
            latencies.append(r.latency_ms)
            in_toks += r.input_tokens
            out_toks += r.output_tokens

    if not latencies:
        raise RuntimeError(f"no latency samples produced from {dataset_path}")

    total_calls = len(latencies)
    total_seconds = sum(latencies) / 1000.0
    summary = {
        "latency_records": n,
        "latency_samples": total_calls,
        "p50_latency_ms": round(statistics.median(latencies), 2),
        "p95_latency_ms": round(_percentile(latencies, 0.95), 2),
        "p99_latency_ms": round(_percentile(latencies, 0.99), 2),
        "tokens_per_second": round(out_toks / total_seconds, 2) if total_seconds > 0 else 0.0,
        "avg_input_tokens": round(in_toks / total_calls, 2),
        "avg_output_tokens": round(out_toks / total_calls, 2),
        "cost_per_1k_requests_usd": round(
            (in_toks / total_calls) * cost_per_1k_input
            + (out_toks / total_calls) * cost_per_1k_output,
            4,
        ),
    }
    out = update_metrics(metrics_path(cfg), summary)
    log.info(
        "latency eval done: p50=%.1fms p95=%.1fms p99=%.1fms tok/s=%.1f",
        summary["p50_latency_ms"],
        summary["p95_latency_ms"],
        summary["p99_latency_ms"],
        summary["tokens_per_second"],
    )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Latency / cost eval.")
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    cfg = load_yaml(args.config)
    run_latency_eval(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
