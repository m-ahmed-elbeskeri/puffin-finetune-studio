"""Scaffold a new puffin project folder from the platform template.

A "scaffolded" project is just an empty directory pre-populated with the
config + contract files every llmops tool reads from:

    configs/      data_contracts/  eval_sets/
    profiles/     dataset_cards/   model_cards/
    data/raw/     .env.example

It does NOT seed any training data — the user brings their own JSONL.
It does NOT copy `src/llmops/`; the platform code is the installed
`llmops` package shared across every project.

The template source is the puffin-finetune-studio repo root the backend
is running from (`settings.repo_root`). One repo can scaffold many
sibling projects.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


# Directories copied verbatim from the template repo. Anything not on
# this list (artifacts/, mlruns/, .venv/, the train/eval source code,
# the copilot itself) is intentionally skipped.
_TEMPLATE_DIRS: tuple[str, ...] = (
    "configs",
    "profiles",
    "data_contracts",
    "eval_sets",
    "dataset_cards",
    "model_cards",
)

# Top-level files copied if they exist in the template.
_TEMPLATE_FILES: tuple[str, ...] = (
    ".env.example",
)

# Patterns inside copied dirs that we skip (generated output, not template).
_SKIP_NAMES: frozenset[str] = frozenset({
    "__pycache__", "generated.md", ".DS_Store",
})

_DATA_RAW_README = """\
# Raw training data

Put one or more JSONL files in this directory, then point `configs/data.yaml`
at them under `sources:` and run the data pipeline:

```
puffin data validate
puffin data build
```

Schema is enforced from `data_contracts/sft_schema.json` (chat-style) or
`dataset_contracts/preference_schema.json` (DPO). Records that fail
validation are dropped before training, with a count logged.
"""


@dataclass(frozen=True)
class ScaffoldResult:
    target_path: str
    files_copied: list[str]
    dirs_created: list[str]
    skipped: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "target_path": self.target_path,
            "files_copied": self.files_copied,
            "dirs_created": self.dirs_created,
            "skipped": self.skipped,
        }


def _iter_copy(src: Path, dst: Path, skipped: list[str]) -> Iterable[Path]:
    """Recursive copy that skips `_SKIP_NAMES` entries. Yields each file
    actually written, relative to `dst`, so callers can build a manifest."""
    if src.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        yield dst
        return
    for entry in src.iterdir():
        if entry.name in _SKIP_NAMES:
            skipped.append(str(entry))
            continue
        target = dst / entry.name
        if entry.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            yield from _iter_copy(entry, target, skipped)
        else:
            shutil.copy2(entry, target)
            yield target


def scaffold_project(
    *,
    template_root: Path,
    target_path: Path,
) -> ScaffoldResult:
    """Copy the template into `target_path`. Refuses to overwrite an
    existing non-empty directory. Creates the dir if it doesn't exist."""
    template_root = Path(template_root).expanduser().resolve()
    target = Path(target_path).expanduser().resolve()

    if not template_root.exists():
        raise ValueError(f"template root does not exist: {template_root}")
    if target == template_root:
        raise ValueError("target path is the template itself — pick another folder")

    if target.exists():
        if not target.is_dir():
            raise ValueError(f"target exists and is not a directory: {target}")
        if any(target.iterdir()):
            raise ValueError(
                f"target is not empty: {target}. Pick a new folder or empty this one first."
            )
    else:
        target.mkdir(parents=True, exist_ok=False)

    files_copied: list[str] = []
    dirs_created: list[str] = []
    skipped: list[str] = []

    for d in _TEMPLATE_DIRS:
        src = template_root / d
        if not src.exists():
            skipped.append(d)
            continue
        dst = target / d
        dst.mkdir(parents=True, exist_ok=True)
        dirs_created.append(d)
        for written in _iter_copy(src, dst, skipped):
            files_copied.append(str(written.relative_to(target)))

    for f in _TEMPLATE_FILES:
        src = template_root / f
        if not src.exists():
            skipped.append(f)
            continue
        dst = target / f
        shutil.copy2(src, dst)
        files_copied.append(str(dst.relative_to(target)))

    # Always create an empty data/raw/ plus the placeholder README so the
    # picker can land here and `dataset_audit` / `project_status` work.
    raw = target / "data" / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "README.md").write_text(_DATA_RAW_README, encoding="utf-8")
    dirs_created.append("data/raw")
    files_copied.append("data/raw/README.md")

    # Pre-create artifacts/ too — every tool that writes (train_start,
    # gate_apply, deploy_push) assumes it exists.
    (target / "artifacts").mkdir(exist_ok=True)
    dirs_created.append("artifacts")

    return ScaffoldResult(
        target_path=str(target),
        files_copied=sorted(files_copied),
        dirs_created=sorted(set(dirs_created)),
        skipped=skipped,
    )
