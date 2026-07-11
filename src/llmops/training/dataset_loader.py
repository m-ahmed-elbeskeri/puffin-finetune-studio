"""Convert canonical SFT JSONL records into a training-text Dataset.

Uses the SHARED `build_training_text` from `llmops.features.prompt_builder` so
the supervised text is byte-identical to what the inference pipeline sees at
serving time. This is the load-bearing anti-skew step.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from llmops.data.io_utils import read_jsonl
from llmops.features.chat_template import DEFAULT_CHAT_TEMPLATE_VERSION
from llmops.features.prompt_builder import build_training_text
from llmops.features.schemas import Message


def _record_to_text(record: dict[str, Any], *, chat_template_version: str, eos_token: str) -> str:
    messages = [Message(**m) for m in record["messages"]]
    return build_training_text(
        messages,
        chat_template_version=chat_template_version,
        eos_token=eos_token,
    )


def jsonl_to_text_iter(
    path: str | Path,
    *,
    chat_template_version: str = DEFAULT_CHAT_TEMPLATE_VERSION,
    eos_token: str = "</s>",
) -> Iterator[dict[str, str]]:
    """Yield {'text': ...} records ready for SFTTrainer."""
    for record in read_jsonl(path):
        text = _record_to_text(
            record,
            chat_template_version=chat_template_version,
            eos_token=eos_token,
        )
        yield {"text": text}


def load_text_dataset(
    train_path: str | Path,
    eval_path: str | Path | None,
    *,
    chat_template_version: str,
    eos_token: str,
    limit: int | None = None,
) -> Any:
    """Materialize HF Datasets with `text` column. Lazy import of `datasets`."""
    from datasets import Dataset, DatasetDict

    train_records = list(
        jsonl_to_text_iter(
            train_path,
            chat_template_version=chat_template_version,
            eos_token=eos_token,
        )
    )
    if limit is not None:
        train_records = train_records[:limit]

    splits: dict[str, Any] = {"train": Dataset.from_list(train_records)}
    if eval_path is not None and Path(eval_path).exists():
        eval_records = list(
            jsonl_to_text_iter(
                eval_path,
                chat_template_version=chat_template_version,
                eos_token=eos_token,
            )
        )
        if limit is not None:
            eval_records = eval_records[: max(1, limit // 4)]
        splits["eval"] = Dataset.from_list(eval_records)
    return DatasetDict(splits)
