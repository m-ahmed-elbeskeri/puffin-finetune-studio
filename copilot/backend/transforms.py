"""Custom pipeline transform scripts — list / read / save / delete / run.

Scripts live in ``<repo>/data/transforms/*.py`` and follow one contract::

    python <script>.py --input <in.jsonl> --output <out.jsonl>

They are pre-processing steps the user (or the AI side panel) authors to
reshape raw data before the standard pipeline runs — schema mapping,
filtering, cleaning. The Data page manages them; *execution* is gated by
the same dangerous-tools flag as the pipeline itself, saving is not
(a saved script does nothing until explicitly run).
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

NAME_RE = re.compile(r"^[A-Za-z0-9_\-]+\.py$")
MAX_CONTENT_BYTES = 200_000
RUN_TIMEOUT_S = 300.0
MAX_CHAIN_STEPS = 20
_TAIL_LINES = 40
_ORDER_FILE = ".pipeline.json"


class TransformError(ValueError):
    """Invalid request (bad name, bad path, bad content) — maps to HTTP 400."""


def transforms_dir(repo_root: Path) -> Path:
    return Path(repo_root) / "data" / "transforms"


def _safe_script_path(repo_root: Path, name: str) -> Path:
    if not NAME_RE.match(name or ""):
        raise TransformError(
            "script name must be <letters/digits/_/-> ending in .py")
    d = transforms_dir(repo_root).resolve()
    p = (d / name).resolve()
    if not str(p).startswith(str(d)):
        raise TransformError("path escapes data/transforms/")
    return p


def _first_description(text: str) -> str:
    """First docstring line (or first comment) — the UI's list subtitle."""
    m = re.match(r'\s*(?:"""|\'\'\')(.*?)(?:"""|\'\'\')', text, re.S)
    if m:
        for line in m.group(1).strip().splitlines():
            line = line.strip()
            if line:
                return line[:160]
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#"):
            cleaned = s.lstrip("#").strip()
            if cleaned:
                return cleaned[:160]
        elif s:
            break
    return ""


def _order_path(repo_root: Path) -> Path:
    return transforms_dir(repo_root) / _ORDER_FILE


def read_order(repo_root: Path) -> list[str]:
    """Saved run order, filtered to scripts that still exist."""
    p = _order_path(repo_root)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    order = data.get("order") if isinstance(data, dict) else None
    if not isinstance(order, list):
        return []
    existing = {q.name for q in transforms_dir(repo_root).glob("*.py")}
    return [n for n in order if isinstance(n, str) and n in existing]


def _ordered_names(repo_root: Path) -> list[str]:
    """Every script name in saved order, with any not-yet-ordered files
    (freshly created) appended alphabetically so nothing is ever hidden."""
    d = transforms_dir(repo_root)
    if not d.exists():
        return []
    on_disk = sorted(q.name for q in d.glob("*.py"))
    saved = read_order(repo_root)
    seen = set(saved)
    return saved + [n for n in on_disk if n not in seen]


def write_order(repo_root: Path, names: list[str]) -> list[str]:
    """Persist the run order. Silently drops names that aren't real scripts;
    any existing script left out is appended so it can't disappear."""
    d = transforms_dir(repo_root)
    on_disk = {q.name for q in d.glob("*.py")} if d.exists() else set()
    ordered = [n for n in names if isinstance(n, str) and n in on_disk]
    seen = set(ordered)
    ordered += [n for n in sorted(on_disk) if n not in seen]
    d.mkdir(parents=True, exist_ok=True)
    _order_path(repo_root).write_text(
        json.dumps({"order": ordered}, indent=2), encoding="utf-8")
    return ordered


def list_transforms(repo_root: Path) -> list[dict[str, Any]]:
    d = transforms_dir(repo_root)
    out: list[dict[str, Any]] = []
    if not d.exists():
        return out
    for name in _ordered_names(repo_root):
        p = d / name
        try:
            stat = p.stat()
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        out.append({
            "name": p.name,
            "size_bytes": stat.st_size,
            "mtime": _dt.datetime.fromtimestamp(
                stat.st_mtime, tz=_dt.timezone.utc).isoformat(timespec="seconds"),
            "description": _first_description(text),
        })
    return out


def read_transform(repo_root: Path, name: str) -> dict[str, Any]:
    p = _safe_script_path(repo_root, name)
    if not p.exists():
        raise FileNotFoundError(name)
    return {"name": p.name, "content": p.read_text(encoding="utf-8")}


def save_transform(repo_root: Path, name: str, content: str) -> dict[str, Any]:
    p = _safe_script_path(repo_root, name)
    raw = content.encode("utf-8")
    if not content.strip():
        raise TransformError("content cannot be empty")
    if len(raw) > MAX_CONTENT_BYTES:
        raise TransformError(
            f"content too large ({len(raw)} bytes > {MAX_CONTENT_BYTES})")

    warnings: list[str] = []
    if "--input" not in content or "--output" not in content:
        warnings.append(
            "Script doesn't mention --input/--output — the runner invokes it "
            "as `python script.py --input <in> --output <out>`.")

    p.parent.mkdir(parents=True, exist_ok=True)
    backup: str | None = None
    if p.exists():
        bak = p.with_suffix(".py.bak")
        bak.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
        backup = bak.name
    p.write_text(content, encoding="utf-8")
    return {
        "name": p.name,
        "size_bytes": len(raw),
        "backup": backup,
        "warnings": warnings,
        "description": _first_description(content),
    }


def delete_transform(repo_root: Path, name: str) -> bool:
    p = _safe_script_path(repo_root, name)
    if not p.exists():
        raise FileNotFoundError(name)
    p.unlink()
    bak = p.with_suffix(".py.bak")
    if bak.exists():
        bak.unlink()
    return True


_DATA_ROOTS = ("data", "eval_sets")


def _resolve_jsonl(repo_root: Path, rel: str, *, roots: tuple[str, ...],
                   must_exist: bool) -> Path:
    if not str(rel).lower().endswith(".jsonl"):
        raise TransformError(f"{rel!r}: only .jsonl files are supported")
    p = (Path(repo_root) / rel).resolve()
    allowed = [str((Path(repo_root) / r).resolve()) for r in roots]
    if not any(str(p).startswith(a) for a in allowed):
        raise TransformError(
            f"{rel!r} is outside the allowed folders ({', '.join(roots)}/)")
    if must_exist and not p.exists():
        raise FileNotFoundError(rel)
    return p


def _count_lines(path: Path) -> int:
    n = 0
    with path.open("rb") as fh:
        for _ in fh:
            n += 1
    return n


async def _exec_script(
    repo_root: Path, script: Path, inp: Path, outp: Path, timeout_s: float,
) -> dict[str, Any]:
    """Run one script from an absolute input to an absolute output path.

    Returns exit code, timing, stdout tail, and whether the output landed.
    Caller owns all path validation.
    """
    outp.parent.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PYTHONUTF8": "1"}
    started = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        sys.executable, str(script),
        "--input", str(inp), "--output", str(outp),
        cwd=str(repo_root),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
    )
    timed_out = False
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        timed_out = True
        proc.kill()
        out, _ = await proc.communicate()
    duration = time.monotonic() - started

    text = out.decode("utf-8", errors="replace") if out else ""
    tail = "\n".join(text.splitlines()[-_TAIL_LINES:])
    exit_code = proc.returncode if not timed_out else -1
    output_exists = outp.exists()
    return {
        "exit_code": exit_code,
        "ok": (exit_code == 0) and not timed_out and output_exists,
        "timed_out": timed_out,
        "stdout_tail": tail,
        "output_exists": output_exists,
        "output_lines": _count_lines(outp) if output_exists else 0,
        "duration_s": round(duration, 2),
    }


async def run_transform(
    repo_root: Path,
    name: str,
    input_rel: str,
    output_rel: str | None = None,
    *,
    timeout_s: float = RUN_TIMEOUT_S,
) -> dict[str, Any]:
    """Run ``python <script> --input <in> --output <out>`` inside the repo.

    Input must live under data/ or eval_sets/; output is jailed to data/.
    """
    script = _safe_script_path(repo_root, name)
    if not script.exists():
        raise FileNotFoundError(name)

    inp = _resolve_jsonl(repo_root, input_rel, roots=_DATA_ROOTS, must_exist=True)
    if not output_rel:
        output_rel = f"data/raw/{inp.stem}__{script.stem}.jsonl"
    outp = _resolve_jsonl(repo_root, output_rel, roots=("data",), must_exist=False)
    if outp == inp:
        raise TransformError("output must differ from input")

    run = await _exec_script(repo_root, script, inp, outp, timeout_s)
    return {
        "kind": "transform_run_result",
        "script": script.name,
        "input": input_rel,
        "output": str(outp.relative_to(Path(repo_root))).replace("\\", "/"),
        **run,
    }


async def run_chain(
    repo_root: Path,
    steps: list[str],
    input_rel: str,
    output_rel: str | None = None,
    *,
    timeout_s: float = RUN_TIMEOUT_S,
) -> dict[str, Any]:
    """Run several scripts in order, piping each output into the next input.

    The user's input file and the final output are validated/jailed like a
    single run; the intermediate files live in a scratch dir and never touch
    the project. Stops at the first failing step.
    """
    if not steps:
        raise TransformError("no steps to run")
    if len(steps) > MAX_CHAIN_STEPS:
        raise TransformError(f"too many steps (max {MAX_CHAIN_STEPS})")
    scripts = [_safe_script_path(repo_root, n) for n in steps]
    for s, n in zip(scripts, steps):
        if not s.exists():
            raise FileNotFoundError(n)

    inp = _resolve_jsonl(repo_root, input_rel, roots=_DATA_ROOTS, must_exist=True)
    if not output_rel:
        stem = re.sub(r"[^A-Za-z0-9_-]+", "-", "-".join(s.stem for s in scripts))[:60]
        output_rel = f"data/raw/{inp.stem}__{stem or 'chain'}.jsonl"
    final_out = _resolve_jsonl(repo_root, output_rel, roots=("data",), must_exist=False)

    scratch = Path(tempfile.mkdtemp(prefix="puffin_chain_"))
    step_results: list[dict[str, Any]] = []
    all_ok = True
    try:
        cur_in = inp
        for i, (script, name) in enumerate(zip(scripts, steps)):
            last = i == len(scripts) - 1
            cur_out = final_out if last else (scratch / f"step{i}.jsonl")
            run = await _exec_script(repo_root, script, cur_in, cur_out, timeout_s)
            step_results.append({
                "script": name,
                "input_lines": _count_lines(cur_in) if cur_in.exists() else 0,
                **run,
            })
            if not run["ok"]:
                all_ok = False
                break
            cur_in = cur_out
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    return {
        "kind": "transform_chain_result",
        "steps": step_results,
        "all_ok": all_ok,
        "input": input_rel,
        "output": str(final_out.relative_to(Path(repo_root))).replace("\\", "/"),
        "output_exists": final_out.exists() and all_ok,
        "output_lines": _count_lines(final_out) if (final_out.exists() and all_ok) else 0,
    }
