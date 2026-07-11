"""Prometheus metrics with a graceful no-op fallback.

If `prometheus_client` is not installed (for example in a minimal eval-only
install), every metric still imports and `.inc()` / `.observe()` calls become
no-ops, and `/metrics` returns an empty registry.
"""
from __future__ import annotations

from typing import Any

try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        CollectorRegistry,
        Counter,
        Histogram,
        generate_latest,
    )

    _PROM_OK = True
    REGISTRY: Any = CollectorRegistry(auto_describe=True)
except ImportError:  # pragma: no cover

    class _NoLabel:
        def labels(self, *_a: Any, **_kw: Any) -> _NoLabel:
            return self

        def inc(self, *_a: Any, **_kw: Any) -> None:
            pass

        def observe(self, *_a: Any, **_kw: Any) -> None:
            pass

    Counter = Histogram = lambda *_a, **_kw: _NoLabel()  # type: ignore
    REGISTRY = None
    CONTENT_TYPE_LATEST = "text/plain"
    _PROM_OK = False

    def generate_latest(_reg: Any = None) -> bytes:
        return b""


_BUCKETS_LATENCY = (0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 8.0, 13.0, 21.0)


inference_counter = Counter(
    "puffin_inference_requests_total",
    "Total chat completion requests served.",
    ["model", "backend"],
    registry=REGISTRY if _PROM_OK else None,
)

inference_errors = Counter(
    "puffin_inference_errors_total",
    "Errors during inference, by reason.",
    ["reason"],
    registry=REGISTRY if _PROM_OK else None,
)

inference_latency = Histogram(
    "puffin_inference_latency_seconds",
    "Latency of chat completion requests (end-to-end pipeline).",
    ["model"],
    buckets=_BUCKETS_LATENCY,
    registry=REGISTRY if _PROM_OK else None,
)

inference_tokens = Counter(
    "puffin_inference_tokens_total",
    "Total tokens processed, split by kind.",
    ["model", "kind"],
    registry=REGISTRY if _PROM_OK else None,
)

feedback_counter = Counter(
    "puffin_feedback_total",
    "User feedback signals received.",
    ["score"],
    registry=REGISTRY if _PROM_OK else None,
)


def render_prometheus(registry: Any = None) -> str:
    if not _PROM_OK:
        return ""
    return generate_latest(registry or REGISTRY).decode("utf-8")
