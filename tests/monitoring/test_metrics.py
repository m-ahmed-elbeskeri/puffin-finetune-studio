from __future__ import annotations

from llmops.monitoring import metrics as m


def test_inference_counter_smoke():
    # Should not raise whether prometheus_client is installed or not.
    m.inference_counter.labels(model="x", backend="echo").inc()
    m.inference_errors.labels(reason="r").inc()
    m.inference_latency.labels(model="x").observe(0.5)
    m.inference_tokens.labels(model="x", kind="prompt").inc(10)


def test_render_prometheus_returns_string():
    out = m.render_prometheus(m.REGISTRY)
    assert isinstance(out, str)
