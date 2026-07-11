"""Data inspection: the analyses a fine-tuning engineer runs before trusting a
dataset.

Everything here is read-only. Five reports:

- tokens:      real-tokenizer counts, truncation risk, tokens/epoch + rough cost
- template:    render one record through the chat template + show the loss mask
- quality:     empty/short replies, role alternation, refusal rate, turn mix,
               and preference-pair checks for DPO data
- leakage:     exact + prompt overlap across train/eval/test and eval_sets
- fingerprint: content hash of each split + the lineage that produced it

The tokenizer is optional. If transformers or the model can't be loaded we fall
back to a char-based estimate and say so, so the reports always render.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterator

# --------------------------------------------------------------------------
# shared helpers
# --------------------------------------------------------------------------
_REFUSAL_RE = re.compile(
    r"\b(i'm sorry|i am sorry|i cannot|i can't|i can not|i'm unable|i am unable|"
    r"i won't|i will not|as an ai|i'm not able|i am not able|i do not have|"
    r"unable to help|can't help with that|cannot assist)\b",
    re.IGNORECASE,
)
_DEFAULT_MODEL = "HuggingFaceTB/SmolLM2-135M-Instruct"
_DEFAULT_MAX_SEQ = 4096
# Rough blended $/1M-token training cost for a small LoRA run on a rented GPU.
# Only used for a ballpark; the UI labels it an estimate.
_COST_PER_MTOK = 0.05

_tokenizer_cache: dict[str, Any] = {}


class InspectError(ValueError):
    """Bad request (maps to HTTP 400)."""


def _resolve(repo_root: Path, rel: str, *, roots: tuple[str, ...] = ("data", "eval_sets")) -> Path:
    if not str(rel).lower().endswith(".jsonl"):
        raise InspectError(f"{rel!r}: only .jsonl files can be inspected")
    p = (Path(repo_root) / rel).resolve()
    allowed = [str((Path(repo_root) / r).resolve()) for r in roots]
    if not any(str(p).startswith(a) for a in allowed):
        raise InspectError(f"{rel!r} is outside the allowed folders")
    if not p.exists():
        raise FileNotFoundError(rel)
    return p


def _iter_jsonl(path: Path, limit: int | None = None) -> Iterator[dict]:
    with path.open("r", encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            if limit is not None and i >= limit:
                break
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                yield obj


def _count_lines(path: Path) -> int:
    n = 0
    with path.open("rb") as fh:
        for _ in fh:
            n += 1
    return n


def _train_cfg(repo_root: Path) -> dict[str, Any]:
    p = Path(repo_root) / "configs" / "train.yaml"
    out = {"base_model": _DEFAULT_MODEL, "max_seq_length": _DEFAULT_MAX_SEQ}
    if not p.exists():
        return out
    try:
        import yaml
        cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return out
    model = cfg.get("model") or {}
    training = cfg.get("training") or {}
    if isinstance(model.get("base_model"), str):
        out["base_model"] = model["base_model"]
    for src in (training, model, cfg):
        v = src.get("max_seq_length") if isinstance(src, dict) else None
        if isinstance(v, int) and v > 0:
            out["max_seq_length"] = v
            break
    return out


def _get_tokenizer(model_id: str):
    """Cached tokenizer, or None if transformers/model unavailable."""
    if model_id in _tokenizer_cache:
        return _tokenizer_cache[model_id]
    tok = None
    try:
        from transformers import AutoTokenizer
        tok = AutoTokenizer.from_pretrained(model_id)
    except Exception:  # noqa: BLE001 - offline, missing dep, gated model, etc.
        tok = None
    _tokenizer_cache[model_id] = tok
    return tok


def _count_chat_tokens(tok, msgs: list[dict]) -> int | None:
    """Token count for a conversation under the model's chat template.

    Robust across transformers versions: apply_chat_template(tokenize=True)
    may return a flat list[int], a batched list[list[int]], or a
    BatchEncoding (whose len() is the number of keys, not tokens). We
    normalize all three, and fall back to tokenizing the rendered string.
    """
    try:
        enc = tok.apply_chat_template(msgs, tokenize=True)
    except Exception:  # noqa: BLE001
        return None
    ids = None
    if hasattr(enc, "input_ids"):        # BatchEncoding / dict-like
        ids = enc.input_ids
    elif isinstance(enc, dict):
        ids = enc.get("input_ids")
    elif isinstance(enc, (list, tuple)):
        ids = enc
    if ids is not None:
        if len(ids) and isinstance(ids[0], (list, tuple)):
            ids = ids[0]
        try:
            return int(len(ids))
        except TypeError:
            pass
    # Fallback: render to a string and tokenize that.
    try:
        text = tok.apply_chat_template(msgs, tokenize=False)
        return len(tok(text, add_special_tokens=False)["input_ids"])
    except Exception:  # noqa: BLE001
        return None


def _as_messages(rec: dict) -> list[dict[str, str]] | None:
    """Normalize any supported record into a chat messages list."""
    msgs = rec.get("messages")
    if isinstance(msgs, list) and msgs:
        return [m for m in msgs if isinstance(m, dict)]
    prompt = rec.get("prompt") or rec.get("instruction") or rec.get("question")
    reply = (rec.get("completion") or rec.get("response") or rec.get("output")
             or rec.get("answer") or rec.get("chosen"))
    if prompt is not None and reply is not None:
        out = []
        system = rec.get("system") or rec.get("system_prompt")
        if system:
            out.append({"role": "system", "content": str(system)})
        out.append({"role": "user", "content": str(prompt)})
        out.append({"role": "assistant", "content": str(reply)})
        return out
    return None


def _flat_text(rec: dict) -> str:
    msgs = _as_messages(rec)
    if msgs:
        return "\n".join(str(m.get("content", "")) for m in msgs)
    return json.dumps(rec, ensure_ascii=False)


def _pcts(values: list[int]) -> dict[str, int]:
    if not values:
        return {"p50": 0, "p90": 0, "p99": 0, "max": 0, "mean": 0}
    s = sorted(values)
    n = len(s)

    def at(p: float) -> int:
        return s[max(0, min(n - 1, int(p * (n - 1))))]

    return {
        "p50": at(0.5), "p90": at(0.9), "p99": at(0.99),
        "max": s[-1], "mean": sum(s) // n,
    }


# --------------------------------------------------------------------------
# 1. token analysis
# --------------------------------------------------------------------------
def analyze_tokens(repo_root: Path, rel: str, *, sample_n: int = 400) -> dict[str, Any]:
    path = _resolve(repo_root, rel)
    cfg = _train_cfg(repo_root)
    model_id = cfg["base_model"]
    max_seq = cfg["max_seq_length"]
    tok = _get_tokenizer(model_id)

    total_records = _count_lines(path)
    counts: list[int] = []
    over = 0
    for rec in _iter_jsonl(path, limit=sample_n):
        msgs = _as_messages(rec)
        n: int | None = None
        if tok is not None and msgs:
            n = _count_chat_tokens(tok, msgs)
        if n is None and tok is not None:
            n = len(tok(_flat_text(rec)).get("input_ids", []))
        if n is None:
            n = max(1, len(_flat_text(rec)) // 4)  # ~4 chars/token heuristic
        counts.append(n)
        if n > max_seq:
            over += 1

    sampled = len(counts)
    stats = _pcts(counts)
    mean = stats["mean"]
    est_total_tokens = mean * total_records
    return {
        "kind": "token_report",
        "path": rel,
        "tokenizer": model_id if tok is not None else "estimated (chars/4)",
        "exact": tok is not None,
        "max_seq_length": max_seq,
        "total_records": total_records,
        "sampled": sampled,
        "tokens": stats,
        "over_max_seq": over,
        "over_max_seq_pct": round(100 * over / sampled, 1) if sampled else 0.0,
        "est_tokens_per_epoch": est_total_tokens,
        "est_cost_per_epoch_usd": round(est_total_tokens / 1_000_000 * _COST_PER_MTOK, 4),
        "warnings": _token_warnings(stats, over, sampled, max_seq),
    }


def _token_warnings(stats: dict, over: int, sampled: int, max_seq: int) -> list[str]:
    w: list[str] = []
    if sampled and over:
        pct = 100 * over / sampled
        w.append(
            f"{over}/{sampled} sampled records ({pct:.0f}%) exceed max_seq_length "
            f"({max_seq:,}); they will be truncated during training.")
    if stats["p50"] and stats["p99"] > 6 * stats["p50"]:
        w.append(
            "Very long tail: p99 is more than 6x the median, so a few huge "
            "records dominate the token budget. Consider filtering or trimming them.")
    return w


# --------------------------------------------------------------------------
# 2. chat template + loss mask preview
# --------------------------------------------------------------------------
def template_preview(repo_root: Path, rel: str, *, index: int = 0) -> dict[str, Any]:
    path = _resolve(repo_root, rel)
    cfg = _train_cfg(repo_root)
    tok = _get_tokenizer(cfg["base_model"])

    rec = None
    for i, r in enumerate(_iter_jsonl(path, limit=index + 1)):
        if i == index:
            rec = r
    if rec is None:
        raise InspectError(f"record {index} not found in {rel}")
    msgs = _as_messages(rec)
    if not msgs:
        raise InspectError("record is not a chat/messages record")

    # Segments teach the loss mask: assistant turns are trained on, everything
    # else (system + user) is context the model reads but is not scored on.
    segments = [{
        "role": str(m.get("role", "")),
        "content": str(m.get("content", "")),
        "trained": str(m.get("role", "")) == "assistant",
    } for m in msgs]

    rendered = None
    token_count = None
    if tok is not None:
        try:
            rendered = tok.apply_chat_template(msgs, tokenize=False)
        except Exception:  # noqa: BLE001
            rendered = None
        token_count = _count_chat_tokens(tok, msgs)

    trained_chars = sum(len(s["content"]) for s in segments if s["trained"])
    total_chars = sum(len(s["content"]) for s in segments) or 1
    return {
        "kind": "template_preview",
        "path": rel,
        "index": index,
        "tokenizer": cfg["base_model"] if tok is not None else None,
        "rendered": rendered,
        "token_count": token_count,
        "segments": segments,
        "trained_fraction": round(trained_chars / total_chars, 3),
        "note": (
            "The highlighted assistant turns are what the model is scored on; "
            "system and user turns are context it reads but never trained to "
            "produce. If your reply text is not highlighted, the mask is wrong."
        ),
    }


# --------------------------------------------------------------------------
# 3. format detection — the single source of truth for "what can train on this"
# --------------------------------------------------------------------------
# Each dataset shape maps to the training methods it can feed. Kept here so the
# file browser (dataset_list), the audit, and the UI all agree.
FORMAT_META: dict[str, dict[str, Any]] = {
    "messages": {
        "label": "chat messages", "methods": ["sft"],
        "help": "Chat records with a messages[] list of {role, content}. Ready for SFT.",
    },
    "prompt_completion": {
        "label": "prompt + completion", "methods": ["sft"],
        "help": "Prompt→answer pairs (prompt/completion, instruction/response, …). "
                "Mapped onto the chat template for SFT.",
    },
    "preference": {
        "label": "preference pairs", "methods": ["dpo", "reward"],
        "help": "prompt + chosen + rejected. Feeds DPO and reward-model training.",
    },
    "kto": {
        "label": "labeled (KTO)", "methods": ["kto"],
        "help": "prompt + completion + a boolean label (good/bad). Feeds KTO from "
                "cheap unpaired thumbs-up / thumbs-down feedback.",
    },
    "prompt_only": {
        "label": "prompts only", "methods": ["grpo", "rloo"],
        "help": "Prompts with no target answer (optionally a reward). Feeds online "
                "RL — GRPO / RLOO — where the reward scores sampled completions.",
    },
    "empty": {"label": "empty", "methods": [], "help": "File has no records."},
    "invalid": {"label": "invalid JSON", "methods": [],
                "help": "Rows failed to parse as JSON. Fix or re-export this file."},
    "unknown": {"label": "unrecognized", "methods": [],
                "help": "Rows don't match any known training schema. Preview the file "
                        "or reshape it with a transform script first."},
}

_PROMPT_KEYS = ("prompt", "instruction", "question")
_REPLY_KEYS = ("completion", "response", "output", "answer")


def classify_record(rec: Any) -> str:
    """Classify one record into a FORMAT_META key. Order matters: the most
    specific shapes (preference, KTO) are checked before generic SFT."""
    if not isinstance(rec, dict):
        return "unknown"
    msgs = rec.get("messages")
    if isinstance(msgs, list) and msgs:
        return "messages"
    if "chosen" in rec and "rejected" in rec:
        return "preference"
    # KTO: a per-sample label (bool, or 0/1) that is NOT a preference pair.
    if "label" in rec and isinstance(rec.get("label"), (bool, int)) \
            and ("completion" in rec or any(k in rec for k in _PROMPT_KEYS)):
        return "kto"
    has_prompt = any(k in rec for k in _PROMPT_KEYS)
    has_reply = any(k in rec for k in _REPLY_KEYS) or "chosen" in rec
    if has_prompt and has_reply:
        return "prompt_completion"
    if has_prompt:
        return "prompt_only"
    return "unknown"


def classify_records(records: list[dict]) -> str:
    """Majority format across a sample (files should be homogeneous, but a
    stray row shouldn't flip the verdict)."""
    if not records:
        return "empty"
    counts: dict[str, int] = {}
    for rec in records:
        fmt = classify_record(rec)
        counts[fmt] = counts.get(fmt, 0) + 1
    return max(counts, key=lambda k: counts[k])


# --------------------------------------------------------------------------
# 3b. quality / format + preference checks
# --------------------------------------------------------------------------
def _format_fields(fmt: str) -> dict[str, Any]:
    meta = FORMAT_META.get(fmt, FORMAT_META["unknown"])
    return {"format": fmt, "format_label": meta["label"], "methods": meta["methods"]}


def analyze_quality(repo_root: Path, rel: str, *, sample_n: int = 1000) -> dict[str, Any]:
    path = _resolve(repo_root, rel)
    total = _count_lines(path)
    records = list(_iter_jsonl(path, limit=sample_n))
    if not records:
        return {"kind": "data_quality_report", "path": rel, "total_records": 0,
                "sampled": 0, "schema": "empty", **_format_fields("empty"),
                "warnings": ["File is empty."]}

    fmt = classify_records(records)
    if fmt == "preference":
        report = _preference_quality(rel, total, records)
    elif fmt == "kto":
        report = _kto_quality(rel, total, records)
    elif fmt == "prompt_only":
        report = _prompt_only_quality(rel, total, records)
    else:
        report = _sft_quality(rel, total, records)
    # Attach the canonical format + trainable methods to every report so the
    # UI can show "this file enables SFT / DPO / …" straight from the audit.
    report.update(_format_fields(fmt))
    return report


def _sft_quality(rel: str, total: int, records: list[dict]) -> dict[str, Any]:
    n = len(records)
    empty_assistant = short_assistant = no_assistant = bad_alternation = 0
    refusals = 0
    single_turn = multi_turn = 0
    system_prompts: dict[str, int] = {}
    for rec in records:
        msgs = _as_messages(rec) or []
        roles = [str(m.get("role", "")) for m in msgs]
        asst = [str(m.get("content", "")) for m in msgs if m.get("role") == "assistant"]
        if not asst:
            no_assistant += 1
        else:
            last = asst[-1].strip()
            if not last:
                empty_assistant += 1
            elif len(last) < 10:
                short_assistant += 1
            if _REFUSAL_RE.search(" ".join(asst)):
                refusals += 1
        # role alternation: after an optional leading system, must go
        # user, assistant, user, assistant, ...
        seq = [r for r in roles if r != "system"]
        expected = ["user", "assistant"]
        if any(seq[i] != expected[i % 2] for i in range(len(seq))):
            bad_alternation += 1
        user_turns = sum(1 for r in roles if r == "user")
        if user_turns <= 1:
            single_turn += 1
        else:
            multi_turn += 1
        if msgs and msgs[0].get("role") == "system":
            sp = str(msgs[0].get("content", ""))
            system_prompts[sp] = system_prompts.get(sp, 0) + 1

    top_system = max(system_prompts.values()) if system_prompts else 0
    warnings: list[str] = []
    if empty_assistant:
        warnings.append(
            f"{empty_assistant}/{n} records have an empty final assistant reply; "
            "these teach the model to output nothing and should be dropped.")
    if no_assistant:
        warnings.append(
            f"{no_assistant}/{n} records have no assistant turn at all, so there "
            "is nothing to learn from them.")
    if bad_alternation:
        warnings.append(
            f"{bad_alternation}/{n} records break user/assistant alternation; "
            "the chat template may render them incorrectly.")
    if refusals > n * 0.15:
        warnings.append(
            f"{refusals}/{n} replies look like refusals. Training on many "
            "refusals makes the model over-cautious.")
    if top_system > n * 0.9 and len(system_prompts) == 1:
        warnings.append(
            "Every record shares one identical system prompt. That is fine for a "
            "fixed persona, but the model will not generalize across instructions.")

    return {
        "kind": "data_quality_report",
        "path": rel,
        "schema": "messages",
        "total_records": total,
        "sampled": n,
        "empty_assistant": empty_assistant,
        "short_assistant": short_assistant,
        "no_assistant": no_assistant,
        "bad_alternation": bad_alternation,
        "refusals": refusals,
        "refusal_rate": round(refusals / n, 3),
        "single_turn": single_turn,
        "multi_turn": multi_turn,
        "with_system": sum(system_prompts.values()),
        "distinct_system_prompts": len(system_prompts),
        "warnings": warnings,
    }


def _preference_quality(rel: str, total: int, records: list[dict]) -> dict[str, Any]:
    n = len(records)
    identical = empty_side = chosen_longer = 0
    chosen_lens: list[int] = []
    rejected_lens: list[int] = []
    for rec in records:
        chosen = str(rec.get("chosen", "")).strip()
        rejected = str(rec.get("rejected", "")).strip()
        if not chosen or not rejected:
            empty_side += 1
            continue
        if chosen == rejected:
            identical += 1
            continue  # degenerate pair: not a real preference, skip length stats
        cl, rl = len(chosen), len(rejected)
        chosen_lens.append(cl)
        rejected_lens.append(rl)
        if cl > rl:
            chosen_longer += 1

    valid = len(chosen_lens)
    mean_c = sum(chosen_lens) // valid if valid else 0
    mean_r = sum(rejected_lens) // valid if valid else 0
    longer_frac = round(chosen_longer / valid, 3) if valid else 0.0
    warnings: list[str] = []
    if identical:
        warnings.append(
            f"{identical}/{n} pairs have chosen == rejected; DPO can't learn a "
            "preference from an identical pair, so drop these.")
    if empty_side:
        warnings.append(
            f"{empty_side}/{n} pairs are missing a chosen or rejected side.")
    if valid and longer_frac > 0.8:
        warnings.append(
            f"'chosen' is longer than 'rejected' in {longer_frac*100:.0f}% of "
            "pairs. The model may just learn 'longer = better' (length bias) "
            "rather than real quality.")
    return {
        "kind": "data_quality_report",
        "path": rel,
        "schema": "preference",
        "total_records": total,
        "sampled": n,
        "identical_pairs": identical,
        "empty_side": empty_side,
        "chosen_longer": chosen_longer,
        "chosen_longer_frac": longer_frac,
        "mean_chosen_chars": mean_c,
        "mean_rejected_chars": mean_r,
        "warnings": warnings,
    }


def _kto_quality(rel: str, total: int, records: list[dict]) -> dict[str, Any]:
    """KTO: prompt + completion + boolean label. Needs both classes present."""
    n = len(records)
    positives = negatives = missing_completion = missing_prompt = 0
    for rec in records:
        label = rec.get("label")
        truth = bool(label) if isinstance(label, (bool, int)) else None
        if truth is True:
            positives += 1
        elif truth is False:
            negatives += 1
        if not str(rec.get("completion", "")).strip():
            missing_completion += 1
        if not any(str(rec.get(k, "")).strip() for k in _PROMPT_KEYS):
            missing_prompt += 1

    labeled = positives + negatives
    warnings: list[str] = []
    if labeled == 0:
        warnings.append(
            "No usable boolean labels found. KTO needs a `label` field that is "
            "true (good) or false (bad) on each record.")
    elif positives == 0 or negatives == 0:
        only = "positive" if negatives == 0 else "negative"
        warnings.append(
            f"Every labeled record is {only}. KTO learns from both thumbs-up and "
            "thumbs-down examples, so include some of each.")
    if missing_completion:
        warnings.append(
            f"{missing_completion}/{n} records have no `completion` text to judge.")
    if missing_prompt:
        warnings.append(f"{missing_prompt}/{n} records have no prompt.")
    return {
        "kind": "data_quality_report",
        "path": rel,
        "schema": "kto",
        "total_records": total,
        "sampled": n,
        "positives": positives,
        "negatives": negatives,
        "missing_completion": missing_completion,
        "missing_prompt": missing_prompt,
        "warnings": warnings,
    }


def _prompt_only_quality(rel: str, total: int, records: list[dict]) -> dict[str, Any]:
    """Prompt-only (GRPO / RLOO): prompts, optionally a per-record reward. The
    reward can also come from a trained reward model at train time."""
    n = len(records)
    empty_prompt = duplicate = 0
    with_reward = 0
    seen: set[str] = set()
    for rec in records:
        prompt = next((str(rec.get(k, "")).strip() for k in _PROMPT_KEYS
                       if rec.get(k)), "")
        if not prompt:
            empty_prompt += 1
            continue
        if prompt in seen:
            duplicate += 1
        seen.add(prompt)
        if any(k in rec for k in ("reward", "reward_model", "score")):
            with_reward += 1

    warnings: list[str] = []
    if empty_prompt:
        warnings.append(f"{empty_prompt}/{n} records have no prompt text.")
    if duplicate > n * 0.2:
        warnings.append(
            f"{duplicate}/{n} prompts are duplicates. Online RL explores per "
            "prompt, so near-duplicate prompts waste rollouts.")
    if with_reward == 0:
        warnings.append(
            "No per-record reward field found. That's fine if you'll score "
            "completions with a reward model or a built-in reward function at "
            "train time; otherwise add a `reward`.")
    return {
        "kind": "data_quality_report",
        "path": rel,
        "schema": "prompt_only",
        "total_records": total,
        "sampled": n,
        "empty_prompt": empty_prompt,
        "duplicate_prompts": duplicate,
        "with_reward": with_reward,
        "warnings": warnings,
    }


# --------------------------------------------------------------------------
# 4. leakage / decontamination
# --------------------------------------------------------------------------
def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _record_sig(rec: dict) -> str:
    return hashlib.sha1(_norm(_flat_text(rec)).encode("utf-8")).hexdigest()


def _prompt_sig(rec: dict) -> str | None:
    msgs = _as_messages(rec) or []
    for m in msgs:
        if m.get("role") == "user":
            return hashlib.sha1(_norm(str(m.get("content", ""))).encode("utf-8")).hexdigest()
    return None


def _sig_map(path: Path, cap: int) -> tuple[dict[str, str], dict[str, str]]:
    """Return {record_sig: preview} and {prompt_sig: preview} for a file."""
    rec_sigs: dict[str, str] = {}
    prompt_sigs: dict[str, str] = {}
    for rec in _iter_jsonl(path, limit=cap):
        preview = _flat_text(rec)[:120]
        rec_sigs[_record_sig(rec)] = preview
        ps = _prompt_sig(rec)
        if ps:
            prompt_sigs[ps] = preview
    return rec_sigs, prompt_sigs


def analyze_leakage(repo_root: Path, *, cap: int = 5000) -> dict[str, Any]:
    proc = Path(repo_root) / "data" / "processed"
    splits = {}
    for name in ("train", "eval", "test"):
        p = proc / f"{name}.jsonl"
        if p.exists() and _count_lines(p) > 0:
            splits[name] = _sig_map(p, cap)

    if "train" not in splits:
        return {
            "kind": "data_leakage_report",
            "present": False,
            "message": "Build your splits first, then this checks train, eval, "
                       "and test for overlap.",
            "pairs": [], "warnings": [],
        }

    pairs: list[dict[str, Any]] = []
    examples: list[dict[str, str]] = []

    def compare(a: str, b: str) -> None:
        (a_rec, a_pr), (b_rec, b_pr) = splits[a], splits[b]
        exact = set(a_rec) & set(b_rec)
        prompt = (set(a_pr) & set(b_pr)) - {s for s in exact}
        pairs.append({
            "a": a, "b": b,
            "exact_overlap": len(exact),
            "prompt_overlap": len(prompt),
        })
        for sig in list(exact)[:3]:
            examples.append({"kind": "identical record", "text": a_rec[sig]})
        for sig in list(prompt)[:3]:
            examples.append({"kind": "same prompt", "text": a_pr[sig]})

    names = list(splits)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            compare(names[i], names[j])

    # train vs eval_sets/golden (the gate's task set)
    golden = Path(repo_root) / "eval_sets" / "golden.jsonl"
    if golden.exists() and _count_lines(golden) > 0:
        g_rec, g_pr = _sig_map(golden, cap)
        tr_rec, tr_pr = splits["train"]
        pairs.append({
            "a": "train", "b": "golden",
            "exact_overlap": len(set(tr_rec) & set(g_rec)),
            "prompt_overlap": len((set(tr_pr) & set(g_pr))
                                  - (set(tr_rec) & set(g_rec))),
        })

    warnings: list[str] = []
    total_leak = sum(p["exact_overlap"] + p["prompt_overlap"] for p in pairs)
    for p in pairs:
        if p["exact_overlap"] or p["prompt_overlap"]:
            tail = " against your golden eval set" if p["b"] == "golden" else ""
            warnings.append(
                f"{p['a']} and {p['b']}: {p['exact_overlap']} identical and "
                f"{p['prompt_overlap']} shared-prompt records{tail}. Any overlap "
                "with eval inflates your scores.")
    return {
        "kind": "data_leakage_report",
        "present": True,
        "clean": total_leak == 0,
        "pairs": pairs,
        "examples": examples[:8],
        "capped": cap,
        "warnings": warnings,
    }


# --------------------------------------------------------------------------
# 5. fingerprint + lineage (reproducibility lockfile)
# --------------------------------------------------------------------------
def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def dataset_fingerprint(repo_root: Path) -> dict[str, Any]:
    repo = Path(repo_root)
    splits: dict[str, Any] = {}
    for name in ("train", "eval", "test"):
        p = repo / "data" / "processed" / f"{name}.jsonl"
        if p.exists():
            splits[name] = {
                "records": _count_lines(p),
                "sha256": _sha256(p)[:16],
                "bytes": p.stat().st_size,
            }

    # lineage
    sources = sorted(
        q.name for q in (repo / "data" / "raw").glob("*.jsonl")
    ) if (repo / "data" / "raw").exists() else []
    transforms: list[str] = []
    order_file = repo / "data" / "transforms" / ".pipeline.json"
    if order_file.exists():
        try:
            transforms = json.loads(order_file.read_text(encoding="utf-8")).get("order", [])
        except (OSError, json.JSONDecodeError):
            transforms = []
    if not transforms and (repo / "data" / "transforms").exists():
        transforms = sorted(
            q.name for q in (repo / "data" / "transforms").glob("*.py"))

    split_cfg = {}
    try:
        from copilot.backend import data_authoring
        split_cfg = data_authoring.read_split(repo)
    except Exception:  # noqa: BLE001
        pass

    combined = "|".join(
        f"{k}:{v['sha256']}" for k, v in sorted(splits.items())) or "empty"
    dataset_hash = hashlib.sha256(combined.encode()).hexdigest()[:16]

    return {
        "kind": "dataset_fingerprint",
        "dataset_hash": dataset_hash,
        "splits": splits,
        "built": bool(splits),
        "lineage": {
            "sources": sources,
            "transforms": transforms,
            "split": split_cfg,
        },
    }
