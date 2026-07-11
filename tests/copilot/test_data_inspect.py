"""Data inspection analyses (deterministic parts)."""

from __future__ import annotations

import json

import pytest
from copilot.backend import data_inspect as di


def _write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


pytestmark = pytest.mark.asyncio


async def test_quality_flags_empty_and_refusals(repo):
    rows = [
        {
            "messages": [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hello there friend"},
            ]
        },
        {
            "messages": [{"role": "user", "content": "help"}, {"role": "assistant", "content": ""}]
        },  # empty
        {
            "messages": [
                {"role": "user", "content": "do X"},
                {"role": "assistant", "content": "I'm sorry, I can't help with that."},
            ]
        },
        {"messages": [{"role": "user", "content": "and Y"}]},  # no assistant
    ]
    p = repo / "data" / "raw" / "d.jsonl"
    _write(p, rows)
    r = di.analyze_quality(repo, "data/raw/d.jsonl")
    assert r["schema"] == "messages"
    assert r["empty_assistant"] == 1
    assert r["no_assistant"] == 1
    assert r["refusals"] == 1
    assert any("empty" in w for w in r["warnings"])


async def test_quality_preference_length_bias(repo):
    rows = [
        {"prompt": "q1", "chosen": "a much longer and better answer here", "rejected": "no"},
        {"prompt": "q2", "chosen": "also clearly longer than the other", "rejected": "nah"},
        {"prompt": "q3", "chosen": "same", "rejected": "same"},  # identical
    ]
    p = repo / "data" / "raw" / "pref.jsonl"
    _write(p, rows)
    r = di.analyze_quality(repo, "data/raw/pref.jsonl")
    assert r["schema"] == "preference"
    assert r["identical_pairs"] == 1
    assert r["chosen_longer_frac"] >= 0.8
    assert any("length bias" in w for w in r["warnings"])


async def test_leakage_catches_planted_overlap(repo):
    shared = {
        "messages": [
            {"role": "user", "content": "leaked question"},
            {"role": "assistant", "content": "leaked answer"},
        ]
    }
    _write(
        repo / "data" / "processed" / "train.jsonl",
        [
            shared,
            {
                "messages": [
                    {"role": "user", "content": "unique train"},
                    {"role": "assistant", "content": "ok"},
                ]
            },
        ],
    )
    _write(
        repo / "data" / "processed" / "eval.jsonl",
        [
            shared,
            {
                "messages": [
                    {"role": "user", "content": "unique eval"},
                    {"role": "assistant", "content": "ok"},
                ]
            },
        ],
    )
    r = di.analyze_leakage(repo)
    assert r["present"] is True
    assert r["clean"] is False
    pair = next(p for p in r["pairs"] if p["a"] == "train" and p["b"] == "eval")
    assert pair["exact_overlap"] == 1
    assert r["warnings"]


async def test_leakage_clean_when_no_overlap(repo):
    _write(
        repo / "data" / "processed" / "train.jsonl",
        [{"messages": [{"role": "user", "content": "a"}, {"role": "assistant", "content": "1"}]}],
    )
    _write(
        repo / "data" / "processed" / "eval.jsonl",
        [{"messages": [{"role": "user", "content": "b"}, {"role": "assistant", "content": "2"}]}],
    )
    r = di.analyze_leakage(repo)
    assert r["present"] is True and r["clean"] is True


async def test_leakage_absent_without_splits(repo):
    r = di.analyze_leakage(repo)
    assert r["present"] is False


async def test_tokens_heuristic_fallback(repo, monkeypatch):
    # Force the no-tokenizer path so the test never touches transformers.
    monkeypatch.setattr(di, "_get_tokenizer", lambda _m: None)
    rows = [
        {
            "messages": [
                {"role": "user", "content": "x" * 40},
                {"role": "assistant", "content": "y" * 40},
            ]
        }
        for _ in range(5)
    ]
    _write(repo / "data" / "raw" / "t.jsonl", rows)
    r = di.analyze_tokens(repo, "data/raw/t.jsonl")
    assert r["exact"] is False
    assert r["tokenizer"].startswith("estimated")
    assert r["total_records"] == 5
    assert r["tokens"]["p50"] > 0
    assert r["est_tokens_per_epoch"] > 0


async def test_template_preview_marks_assistant_trained(repo, monkeypatch):
    monkeypatch.setattr(di, "_get_tokenizer", lambda _m: None)
    rows = [
        {
            "messages": [
                {"role": "system", "content": "be nice"},
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hello"},
            ]
        }
    ]
    _write(repo / "data" / "raw" / "tp.jsonl", rows)
    r = di.template_preview(repo, "data/raw/tp.jsonl", index=0)
    trained = [s for s in r["segments"] if s["trained"]]
    assert len(trained) == 1 and trained[0]["role"] == "assistant"
    assert [s["role"] for s in r["segments"]] == ["system", "user", "assistant"]


class _FakeBatchEncoding:
    """Mimics transformers BatchEncoding: len() is key count, not tokens."""

    def __init__(self, ids):
        self.input_ids = ids
        self._data = {"input_ids": ids, "attention_mask": [1] * len(ids)}

    def __len__(self):
        return len(self._data)  # 2, the trap we must not fall into


class _FakeTok:
    def __init__(self, mode):
        self.mode = mode

    def apply_chat_template(self, msgs, tokenize=True):
        ids = list(range(46))
        if not tokenize:
            return "rendered"
        if self.mode == "batchencoding":
            return _FakeBatchEncoding(ids)
        if self.mode == "nested":
            return [ids]
        return ids  # flat list


@pytest.mark.parametrize("mode", ["batchencoding", "nested", "flat"])
async def test_count_chat_tokens_handles_return_shapes(mode):
    n = di._count_chat_tokens(_FakeTok(mode), [{"role": "user", "content": "hi"}])
    assert n == 46, f"{mode} shape should yield 46 tokens, got {n}"


async def test_fingerprint_hashes_and_lineage(repo):
    _write(
        repo / "data" / "processed" / "train.jsonl",
        [{"messages": [{"role": "user", "content": "a"}]}],
    )
    _write(repo / "data" / "raw" / "src.jsonl", [{"messages": [{"role": "user", "content": "a"}]}])
    r = di.dataset_fingerprint(repo)
    assert r["built"] is True
    assert "train" in r["splits"]
    assert len(r["dataset_hash"]) == 16
    assert "src.jsonl" in r["lineage"]["sources"]
    assert r["lineage"]["split"]["train"] == pytest.approx(0.7)
