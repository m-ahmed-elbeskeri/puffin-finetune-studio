"""Data tools — audit / preview / pipeline run / list / import."""
from __future__ import annotations

import asyncio
import datetime as _dt
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from copilot.backend.tools.registry import ToolContext, ToolError, tool


def _read_jsonl(path: Path, *, limit: int | None = None) -> list[dict]:
    rows: list[dict] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            if limit is not None and i >= limit:
                break
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    n = 0
    with path.open("rb") as fh:
        for _ in fh:
            n += 1
    return n


# ---------------------------------------------------------------------------
# dataset_audit
# ---------------------------------------------------------------------------
class DatasetAuditArgs(BaseModel):
    path: str = Field(
        description="Path to a JSONL file relative to the repo root "
                    "(e.g. 'data/raw/my-tickets.jsonl' or 'data/processed/train.jsonl').",
    )
    sample_n: int = Field(
        default=200, ge=1, le=5000,
        description="How many records to scan for stats. Higher = slower but more accurate.",
    )


@tool(
    "dataset_audit",
    description=(
        "Audit a JSONL dataset (raw or processed). Reports record count, "
        "schema detection (chat/messages vs prompt/completion), length stats, "
        "source/license distribution, and likely PII signals. Use before "
        "kicking off training to validate the data is what you expect."
    ),
    args_model=DatasetAuditArgs,
)
async def dataset_audit(args: DatasetAuditArgs, ctx: ToolContext) -> dict[str, Any]:
    p = (ctx.repo_root / args.path).resolve()
    if not str(p).startswith(str(ctx.repo_root)):
        raise ToolError("path escapes repo root")
    if not p.exists():
        raise ToolError(f"no such file: {args.path}")

    total = _count_lines(p)
    sample = _read_jsonl(p, limit=args.sample_n)
    if not sample:
        return {
            "kind": "dataset_audit",
            "path": args.path, "total_records": 0,
            "warnings": ["File is empty."],
        }

    # Schema detection
    has_messages = any("messages" in r for r in sample)
    has_pc = any(("prompt" in r) and ("completion" in r) for r in sample)
    schema = "messages" if has_messages else ("prompt_completion" if has_pc else "unknown")

    # Length stats (chars across all string content)
    def _total_chars(r: dict) -> int:
        if "messages" in r and isinstance(r["messages"], list):
            return sum(len(m.get("content", "")) for m in r["messages"]
                       if isinstance(m, dict))
        return len(str(r.get("prompt", ""))) + len(str(r.get("completion", "")))

    lens = [_total_chars(r) for r in sample]
    lens.sort()
    n = len(lens)

    def _pct(p: float) -> int:
        if not lens:
            return 0
        i = max(0, min(n - 1, int(p * (n - 1))))
        return lens[i]

    sources = Counter(r.get("source", "—") for r in sample)
    licenses = Counter(r.get("license", "—") for r in sample)

    # Heuristic PII scan (regex over a few fields)
    import re
    EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
    PHONE = re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
    SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
    pii_hits = {"email": 0, "phone": 0, "ssn": 0}
    for r in sample:
        blob = json.dumps(r, default=str)
        if EMAIL.search(blob):
            pii_hits["email"] += 1
        if PHONE.search(blob):
            pii_hits["phone"] += 1
        if SSN.search(blob):
            pii_hits["ssn"] += 1

    warnings: list[str] = []
    if schema == "unknown":
        warnings.append(
            "Schema not recognized — records have neither `messages` nor `prompt`+`completion`."
        )
    if pii_hits["ssn"]:
        warnings.append(f"{pii_hits['ssn']} SSN-shaped strings found — confirm redaction.")
    if pii_hits["email"] > n * 0.05:
        warnings.append(f"{pii_hits['email']}/{n} records contain email addresses.")
    if lens and lens[-1] > 64_000:
        warnings.append(
            f"Max length {lens[-1]:,} chars — may exceed max_seq_length after tokenization."
        )

    return {
        "kind": "dataset_audit",
        "path": args.path,
        "total_records": total,
        "sampled": n,
        "schema": schema,
        "char_length": {
            "p50": _pct(0.5), "p90": _pct(0.9), "p99": _pct(0.99),
            "max": max(lens) if lens else 0, "mean": sum(lens) // n if n else 0,
        },
        "sources": dict(sources.most_common(10)),
        "licenses": dict(licenses.most_common(10)),
        "pii": pii_hits,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# dataset_preview
# ---------------------------------------------------------------------------
class DatasetPreviewArgs(BaseModel):
    path: str
    n: int = Field(default=3, ge=1, le=20)


@tool(
    "dataset_preview",
    description=(
        "Return the first N records of a JSONL dataset so you can show the "
        "user concrete examples (renders as a side-by-side preview card)."
    ),
    args_model=DatasetPreviewArgs,
)
async def dataset_preview(args: DatasetPreviewArgs, ctx: ToolContext) -> dict[str, Any]:
    p = (ctx.repo_root / args.path).resolve()
    if not str(p).startswith(str(ctx.repo_root)):
        raise ToolError("path escapes repo root")
    if not p.exists():
        raise ToolError(f"no such file: {args.path}")
    rows = _read_jsonl(p, limit=args.n)
    return {"kind": "dataset_preview", "path": args.path, "records": rows}


# ---------------------------------------------------------------------------
# data_pipeline_run
# ---------------------------------------------------------------------------
class DataPipelineArgs(BaseModel):
    stages: list[str] = Field(
        default_factory=lambda: [
            "ingest", "validate", "redact_pii", "dedupe", "split",
            "build_dataset_card",
        ],
        description="Stage names to run, in order. Each is a python -m llmops.data.<stage> call.",
    )
    config: str = Field(
        default="configs/data.yaml",
        description="Path to the data-pipeline YAML config.",
    )


@tool(
    "data_pipeline_run",
    description=(
        "Run the data pipeline (ingest → validate → redact → dedupe → split "
        "→ dataset card). Aborts on the first failure. Returns per-stage "
        "exit codes + stdout tail. State-mutating — gated."
    ),
    args_model=DataPipelineArgs,
    dangerous=True,
)
async def data_pipeline_run(args: DataPipelineArgs, ctx: ToolContext) -> dict[str, Any]:
    cfg = (ctx.repo_root / args.config).resolve()
    if not cfg.exists():
        raise ToolError(f"config not found: {args.config}")

    results = []
    for stage in args.stages:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", f"llmops.data.{stage}",
            "--config", str(cfg),
            cwd=str(ctx.repo_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await proc.communicate()
        text = out.decode("utf-8", errors="replace")
        tail = "\n".join(text.splitlines()[-20:])
        results.append({
            "stage": stage,
            "exit_code": proc.returncode,
            "ok": proc.returncode == 0,
            "stdout_tail": tail,
        })
        if proc.returncode != 0:
            break

    return {
        "kind": "data_pipeline_result",
        "stages": results,
        "all_ok": all(r["ok"] for r in results),
    }


# ---------------------------------------------------------------------------
# dataset_list — power the /data page file browser
# ---------------------------------------------------------------------------
def _peek_schema(path: Path) -> str:
    """Classify a file's training format from its first non-empty record.
    Uses the shared classifier so the browser, audit, and UI all agree on the
    format id (messages / prompt_completion / preference / kto / prompt_only)."""
    from copilot.backend.data_inspect import classify_record

    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    return "invalid"
                return classify_record(rec)
    except OSError:
        return "unknown"
    return "empty"


class DatasetListArgs(BaseModel):
    pass


@tool(
    "dataset_list",
    description=(
        "List every JSONL dataset file under the project — raw inputs "
        "(data/raw), processed splits (data/processed), and eval sets "
        "(eval_sets). Returns one entry per file with size, line count, "
        "mtime, and a schema hint so the UI can render a browser."
    ),
    args_model=DatasetListArgs,
)
async def dataset_list(args: DatasetListArgs, ctx: ToolContext) -> dict[str, Any]:  # noqa: ARG001
    repo = Path(ctx.repo_root)
    buckets = [
        ("raw", repo / "data" / "raw"),
        ("interim", repo / "data" / "interim"),
        ("processed", repo / "data" / "processed"),
        ("eval", repo / "eval_sets"),
    ]
    files: list[dict[str, Any]] = []
    for kind, root in buckets:
        if not root.exists():
            continue
        for p in sorted(root.glob("*.jsonl")):
            try:
                stat = p.stat()
            except OSError:
                continue
            files.append({
                "path": str(p.relative_to(repo)).replace("\\", "/"),
                "name": p.name,
                "kind": kind,
                "size_bytes": stat.st_size,
                "mtime": _dt.datetime.fromtimestamp(
                    stat.st_mtime, tz=_dt.timezone.utc,
                ).isoformat(timespec="seconds"),
                "line_count": _count_lines(p),
                "schema_hint": _peek_schema(p),
            })
    return {"kind": "dataset_list", "files": files}


# ---------------------------------------------------------------------------
# dataset_import_hf — pull a HuggingFace dataset into data/raw/ as JSONL
# ---------------------------------------------------------------------------
class DatasetImportHFArgs(BaseModel):
    name: str = Field(
        description=(
            "HuggingFace dataset identifier — 'org/name' or 'name'. "
            "Examples: 'HuggingFaceH4/no_robots', 'tatsu-lab/alpaca'."
        ),
    )
    split: str = Field(
        default="train",
        description="Which split to import (e.g. 'train', 'test', 'validation').",
    )
    max_records: int = Field(
        default=1000, ge=1, le=200_000,
        description="Hard cap on records imported. Streaming = no full download.",
    )
    output_filename: str | None = Field(
        default=None,
        description=(
            "Filename under data/raw/. Defaults to a slug of <name>-<split>. "
            "Must end in .jsonl."
        ),
    )
    subset: str | None = Field(
        default=None,
        description="Optional config/subset name (e.g. 'sst2' for 'glue').",
    )


_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _slugify(s: str) -> str:
    return _SAFE.sub("-", s).strip("-").lower() or "import"


def _coerce_messages(rec: dict[str, Any]) -> dict[str, Any] | None:
    """Map a record to chat-schema {messages: [...]}. Heuristic-only —
    handles the four common HuggingFace shapes; falls through to None
    when nothing matches so the caller can count + report skipped rows."""
    if not isinstance(rec, dict):
        return None
    msgs = rec.get("messages")
    if isinstance(msgs, list) and msgs:
        return {"messages": msgs}
    convo = rec.get("conversations") or rec.get("conversation")
    if isinstance(convo, list) and convo:
        # ShareGPT-style: [{"from": "human"|"gpt", "value": "..."}]
        out: list[dict[str, str]] = []
        role_map = {"human": "user", "user": "user", "gpt": "assistant",
                    "assistant": "assistant", "system": "system"}
        for c in convo:
            if isinstance(c, dict):
                role = role_map.get(str(c.get("from") or c.get("role") or "user"))
                content = c.get("value") or c.get("content") or ""
                if role:
                    out.append({"role": role, "content": str(content)})
        return {"messages": out} if out else None
    prompt = rec.get("prompt") or rec.get("instruction") or rec.get("question")
    response = (
        rec.get("response") or rec.get("completion") or rec.get("output")
        or rec.get("answer") or rec.get("chosen")
    )
    system = rec.get("system") or rec.get("system_prompt")
    if prompt is not None and response is not None:
        msgs = []
        if system:
            msgs.append({"role": "system", "content": str(system)})
        msgs.append({"role": "user", "content": str(prompt)})
        msgs.append({"role": "assistant", "content": str(response)})
        return {"messages": msgs}
    return None


@tool(
    "dataset_import_hf",
    description=(
        "Download a HuggingFace dataset and write it to data/raw/<name>.jsonl "
        "in puffin's chat-message schema. Supports four common source "
        "shapes — messages list, ShareGPT conversations, prompt+completion, "
        "and instruction+response. Records that don't map are skipped and "
        "counted. Hard-capped at max_records so large datasets don't blow "
        "out disk. State-mutating — gated."
    ),
    args_model=DatasetImportHFArgs,
    dangerous=True,
)
async def dataset_import_hf(
    args: DatasetImportHFArgs, ctx: ToolContext,
) -> dict[str, Any]:
    try:
        from datasets import load_dataset
    except ImportError as exc:
        raise ToolError(
            "datasets package not installed. Run: "
            'pip install -e ".[data]"'
        ) from exc

    repo = Path(ctx.repo_root)
    raw_dir = repo / "data" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    fname = args.output_filename
    if not fname:
        fname = f"{_slugify(args.name)}-{_slugify(args.split)}.jsonl"
    if not fname.endswith(".jsonl"):
        fname += ".jsonl"
    # Strip any path components — write strictly inside data/raw/.
    fname = Path(fname).name
    out_path = (raw_dir / fname).resolve()
    if not str(out_path).startswith(str(raw_dir.resolve())):
        raise ToolError(f"refused write outside data/raw/: {fname}")

    def _load() -> tuple[int, int, list[str]]:
        kwargs: dict[str, Any] = {
            "path": args.name,
            "split": args.split,
            "streaming": True,
        }
        if args.subset:
            kwargs["name"] = args.subset
        ds = load_dataset(**kwargs)
        kept = 0
        skipped = 0
        samples: list[str] = []
        with out_path.open("w", encoding="utf-8") as fh:
            for rec in ds:
                mapped = _coerce_messages(rec)
                if mapped is None:
                    skipped += 1
                    continue
                # Preserve a small set of common metadata fields so the
                # validator still has license / source signals.
                for k in ("source", "license", "id", "quality_score"):
                    if k in rec and k not in mapped:
                        mapped[k] = rec[k]
                fh.write(json.dumps(mapped, ensure_ascii=False) + "\n")
                if len(samples) < 3:
                    samples.append(
                        json.dumps(mapped, ensure_ascii=False)[:300],
                    )
                kept += 1
                if kept >= args.max_records:
                    break
        return kept, skipped, samples

    try:
        kept, skipped, samples = await asyncio.to_thread(_load)
    except Exception as exc:  # noqa: BLE001
        raise ToolError(f"HF import failed: {type(exc).__name__}: {exc}") from exc

    return {
        "kind": "dataset_import_result",
        "path": str(out_path.relative_to(repo)).replace("\\", "/"),
        "name": args.name,
        "split": args.split,
        "subset": args.subset,
        "kept": kept,
        "skipped": skipped,
        "samples": samples,
        "message": (
            f"Imported {kept} records from {args.name}/{args.split} "
            f"({skipped} skipped) → {out_path.name}"
        ),
    }
