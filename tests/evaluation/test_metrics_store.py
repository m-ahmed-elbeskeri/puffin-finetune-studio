from __future__ import annotations

from llmops.evaluation.metrics_store import load_metrics, update_metrics


def test_update_metrics_creates_and_merges(tmp_path):
    p = tmp_path / "metrics.json"
    update_metrics(p, {"a": 1})
    update_metrics(p, {"b": 2})
    out = load_metrics(p)
    assert out == {"a": 1, "b": 2}


def test_update_metrics_overwrites_existing_key(tmp_path):
    p = tmp_path / "metrics.json"
    update_metrics(p, {"x": 1})
    update_metrics(p, {"x": 2})
    assert load_metrics(p) == {"x": 2}


def test_load_metrics_missing_returns_empty(tmp_path):
    assert load_metrics(tmp_path / "missing.json") == {}
