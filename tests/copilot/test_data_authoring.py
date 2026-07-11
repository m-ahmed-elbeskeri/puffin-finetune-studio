"""Split-config surgical edits + eval-set authoring."""
from __future__ import annotations

import pytest

from copilot.backend import data_authoring as da


DATA_YAML = """\
name: test
# a comment that must survive
sources: []

max_total_chars: 200000

split:
  train: 0.7
  eval:  0.15
  test:  0.15
  seed: 42
  leakage_threshold: 0.9
  leakage_max: 0

dataset_card: dataset_cards/generated.md
"""


@pytest.fixture
def data_cfg(repo):
    p = repo / "configs" / "data.yaml"
    p.write_text(DATA_YAML, encoding="utf-8")
    return p


def test_read_split(repo, data_cfg):
    s = da.read_split(repo)
    assert s == {"train": 0.7, "eval": 0.15, "test": 0.15, "seed": 42}


def test_read_split_defaults_when_missing(repo):
    (repo / "configs" / "data.yaml").unlink()
    s = da.read_split(repo)
    assert s["train"] == 0.7 and s["seed"] == 42


def test_update_split_preserves_comments_and_other_keys(repo, data_cfg):
    result = da.update_split(
        repo, {"train": 0.8, "eval": 0.1, "test": 0.1, "seed": 7})
    assert result == {"train": 0.8, "eval": 0.1, "test": 0.1, "seed": 7}

    text = data_cfg.read_text(encoding="utf-8")
    assert "# a comment that must survive" in text
    assert "leakage_threshold: 0.9" in text
    assert "dataset_card: dataset_cards/generated.md" in text

    # Re-read through the parser to confirm the new values landed.
    reread = da.read_split(repo)
    assert reread == {"train": 0.8, "eval": 0.1, "test": 0.1, "seed": 7}
    # A .bak of the original was written.
    assert (repo / "configs" / "data.yaml.bak").exists()


def test_update_split_rejects_bad_ratios(repo, data_cfg):
    with pytest.raises(da.AuthoringError):
        da.update_split(repo, {"train": 0.5, "eval": 0.2, "test": 0.2, "seed": 1})
    with pytest.raises(da.AuthoringError):
        da.update_split(repo, {"train": 0, "eval": 0.5, "test": 0.5, "seed": 1})
    with pytest.raises(da.AuthoringError):
        da.update_split(repo, {"train": 0.7, "eval": 0.15, "test": 0.15, "seed": -1})


def test_update_split_missing_block_raises(repo):
    (repo / "configs" / "data.yaml").write_text("name: x\n", encoding="utf-8")
    with pytest.raises(da.AuthoringError):
        da.update_split(repo, {"train": 0.8, "eval": 0.1, "test": 0.1, "seed": 1})


def test_write_eval_set_replace_and_append(repo):
    r1 = da.write_eval_set(
        repo, "golden.jsonl",
        '{"id": "g1", "prompt": "hi"}\n{"id": "g2", "prompt": "yo"}')
    assert r1["total"] == 2 and r1["added"] == 2 and r1["cleared"] is False

    r2 = da.write_eval_set(
        repo, "golden.jsonl", '{"id": "g3", "prompt": "sup"}', mode="append")
    assert r2["total"] == 3 and r2["added"] == 1
    assert (repo / "eval_sets" / "golden.jsonl.bak").exists()

    lines = (repo / "eval_sets" / "golden.jsonl").read_text(
        encoding="utf-8").splitlines()
    assert len(lines) == 3


def test_write_eval_set_clear(repo):
    da.write_eval_set(repo, "safety.jsonl", '{"id": "s1"}')
    r = da.write_eval_set(repo, "safety.jsonl", "")
    assert r["cleared"] is True and r["total"] == 0
    assert (repo / "eval_sets" / "safety.jsonl").read_text(encoding="utf-8") == ""


def test_write_eval_set_validation_and_jail(repo):
    with pytest.raises(da.AuthoringError):
        da.write_eval_set(repo, "golden.jsonl", "not json")
    with pytest.raises(da.AuthoringError):
        da.write_eval_set(repo, "golden.jsonl", '["array not object"]')
    with pytest.raises(da.AuthoringError):
        da.write_eval_set(repo, "../escape.jsonl", '{"id": "x"}')
    with pytest.raises(da.AuthoringError):
        da.write_eval_set(repo, "no_ext", '{"id": "x"}')
