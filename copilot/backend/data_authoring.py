"""Data-authoring helpers for the Data page.

Two focused concerns the copilot's generic tools don't cover:

1. Split ratios — read + surgically update the ``split:`` block in
   configs/data.yaml (train/eval/test/seed) while preserving every comment
   and the rest of the file.
2. Eval sets — write / append / clear JSONL files under eval_sets/, jailed
   to that folder, with per-line JSON validation.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

DATA_CONFIG = "configs/data.yaml"
_EVAL_NAME_RE = re.compile(r"^[A-Za-z0-9_\-]+\.jsonl$")
_SPLIT_KEYS = ("train", "eval", "test")


class AuthoringError(ValueError):
    """Bad request (validation) — maps to HTTP 400."""


# --------------------------------------------------------------------------
# Split config
# --------------------------------------------------------------------------
def _data_config_path(repo_root: Path) -> Path:
    return Path(repo_root) / DATA_CONFIG


def read_split(repo_root: Path) -> dict[str, Any]:
    """Return {train, eval, test, seed} from configs/data.yaml (or defaults)."""
    p = _data_config_path(repo_root)
    defaults = {"train": 0.7, "eval": 0.15, "test": 0.15, "seed": 42}
    if not p.exists():
        return defaults
    import yaml
    try:
        parsed = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise AuthoringError(f"configs/data.yaml is not valid YAML: {exc}") from exc
    split = parsed.get("split") or {}
    out = dict(defaults)
    for k in ("train", "eval", "test"):
        if isinstance(split.get(k), (int, float)):
            out[k] = float(split[k])
    if isinstance(split.get("seed"), int):
        out["seed"] = int(split["seed"])
    return out


def _validate_split(train: float, ev: float, test: float, seed: int) -> None:
    for name, v in (("train", train), ("eval", ev), ("test", test)):
        if not isinstance(v, (int, float)) or v < 0 or v > 1:
            raise AuthoringError(f"{name} ratio must be between 0 and 1")
    if train <= 0:
        raise AuthoringError("train ratio must be greater than 0")
    total = train + ev + test
    if abs(total - 1.0) > 1e-3:
        raise AuthoringError(
            f"ratios must sum to 1.0 (got {total:.3f}) — "
            f"train {train:.3f} + eval {ev:.3f} + test {test:.3f}")
    if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
        raise AuthoringError("seed must be a non-negative integer")


def _fmt_ratio(v: float) -> str:
    # Trim trailing zeros but keep at least one decimal (0.7 -> "0.7").
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return s if "." in s else f"{s}.0"


def _update_split_block(text: str, values: dict[str, Any]) -> str:
    """Surgically replace scalar values inside the top-level ``split:`` block.

    Preserves comments and everything outside the block. Raises if the block
    isn't found so we never write a malformed config.
    """
    lines = text.splitlines(keepends=True)
    start = None
    for i, line in enumerate(lines):
        if re.match(r"^split:\s*(#.*)?$", line.rstrip("\n")):
            start = i
            break
    if start is None:
        raise AuthoringError("no `split:` block found in configs/data.yaml")

    key_val = {
        "train": _fmt_ratio(float(values["train"])),
        "eval": _fmt_ratio(float(values["eval"])),
        "test": _fmt_ratio(float(values["test"])),
        "seed": str(int(values["seed"])),
    }
    seen: set[str] = set()
    i = start + 1
    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()
        # End of block: a non-indented, non-blank line.
        if stripped and not raw[:1].isspace():
            break
        m = re.match(r"^(\s+)(train|eval|test|seed):[ \t]*([^\n#]*)(#.*)?$", raw)
        if m and m.group(2) in key_val:
            indent, key, _old, comment = m.groups()
            comment = comment or ""
            tail = f"  {comment.strip()}" if comment.strip() else ""
            newline = "\n" if raw.endswith("\n") else ""
            lines[i] = f"{indent}{key}: {key_val[key]}{tail}{newline}"
            seen.add(key)
        i += 1

    missing = [k for k in key_val if k not in seen]
    if missing:
        # Insert the missing keys right after the split: line.
        indent = "  "
        m2 = re.match(r"^(\s+)\S", lines[start + 1]) if start + 1 < len(lines) else None
        if m2:
            indent = m2.group(1)
        insert = "".join(
            f"{indent}{k}: {key_val[k]}\n" for k in missing)
        lines.insert(start + 1, insert)
    return "".join(lines)


def update_split(repo_root: Path, values: dict[str, Any]) -> dict[str, Any]:
    """Validate + write new split ratios into configs/data.yaml (with .bak)."""
    try:
        train = float(values.get("train"))
        ev = float(values.get("eval"))
        test = float(values.get("test"))
        seed = int(values.get("seed", 42))
    except (TypeError, ValueError) as exc:
        raise AuthoringError("train/eval/test must be numbers, seed an int") from exc
    _validate_split(train, ev, test, seed)

    p = _data_config_path(repo_root)
    if not p.exists():
        raise AuthoringError("configs/data.yaml not found")
    text = p.read_text(encoding="utf-8")
    new_text = _update_split_block(
        text, {"train": train, "eval": ev, "test": test, "seed": seed})

    import yaml
    try:
        yaml.safe_load(new_text)  # never write a file we can't parse back
    except yaml.YAMLError as exc:
        raise AuthoringError(f"internal: produced invalid YAML ({exc})") from exc

    p.with_suffix(".yaml.bak").write_text(text, encoding="utf-8")
    p.write_text(new_text, encoding="utf-8")
    return {"train": train, "eval": ev, "test": test, "seed": seed}


# --------------------------------------------------------------------------
# Eval sets
# --------------------------------------------------------------------------
def _eval_path(repo_root: Path, name: str) -> Path:
    if not _EVAL_NAME_RE.match(name or ""):
        raise AuthoringError(
            "eval set name must be <letters/digits/_/-> ending in .jsonl")
    d = (Path(repo_root) / "eval_sets").resolve()
    p = (d / name).resolve()
    if not str(p).startswith(str(d)):
        raise AuthoringError("path escapes eval_sets/")
    return p


def _validate_jsonl(content: str) -> tuple[int, int]:
    """Return (valid, invalid) line counts. Raises if a line isn't a JSON obj."""
    valid = invalid = 0
    for n, line in enumerate(content.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AuthoringError(f"line {n} is not valid JSON: {exc.msg}") from exc
        if not isinstance(obj, dict):
            raise AuthoringError(f"line {n} must be a JSON object, not {type(obj).__name__}")
        valid += 1
    return valid, invalid


def write_eval_set(
    repo_root: Path, name: str, content: str, *, mode: str = "replace",
) -> dict[str, Any]:
    """Replace or append JSONL cases in eval_sets/<name>.

    mode='replace' overwrites (empty content clears the file — this is how the
    UI removes the shipped demo cases); mode='append' adds to the tail.
    """
    p = _eval_path(repo_root, name)
    if mode not in ("replace", "append"):
        raise AuthoringError("mode must be 'replace' or 'append'")
    added, _ = _validate_jsonl(content)

    p.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if p.exists():
        backup = p.with_suffix(".jsonl.bak")
        backup.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")

    normalized = content.strip()
    if mode == "append":
        existing = p.read_text(encoding="utf-8") if p.exists() else ""
        existing = existing.rstrip("\n")
        pieces = [x for x in (existing, normalized) if x]
        final = ("\n".join(pieces) + "\n") if pieces else ""
    else:
        final = (normalized + "\n") if normalized else ""
    p.write_text(final, encoding="utf-8")

    total = sum(1 for line in final.splitlines() if line.strip())
    return {
        "name": p.name,
        "mode": mode,
        "added": added,
        "total": total,
        "backup": backup.name if backup else None,
        "cleared": total == 0,
    }
