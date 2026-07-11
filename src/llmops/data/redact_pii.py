"""Regex + heuristic PII redaction.

Scope: emails, phone numbers, US SSNs, credit-card-like numbers, IPv4 addresses,
common API key prefixes (sk-, pk_, AKIA, AIza, ghp_, xoxb-). Names are NOT
redacted by regex (too many false positives) — supply an explicit `pii.deny_terms`
list in `configs/data.yaml` for entity-level redaction.

The Luhn check filters credit-card false positives.

Sets `contains_pii=true` on any record where at least one redaction occurred.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any, Iterator

from llmops.common.config import load_yaml
from llmops.common.logging import get_logger
from llmops.data.io_utils import read_jsonl, write_jsonl

log = get_logger(__name__)


_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{2,4}\)?[\s.-]?){2,4}\d{2,4}(?!\d)"
)
_SSN_RE = re.compile(r"\b(?!000|666|9\d{2})\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b")
_CC_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_IPV4_RE = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b")
_API_KEY_RE = re.compile(
    r"\b(?:sk-[A-Za-z0-9]{20,}|pk_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}|ghp_[A-Za-z0-9]{36}|xoxb-[A-Za-z0-9-]{20,})\b"
)


def _luhn_valid(digits: str) -> bool:
    nums = [int(c) for c in digits if c.isdigit()]
    if not (13 <= len(nums) <= 19):
        return False
    checksum = 0
    parity = len(nums) % 2
    for i, d in enumerate(nums):
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


def _redact_phone_safely(match: re.Match[str]) -> str:
    candidate = match.group(0)
    digits = re.sub(r"\D", "", candidate)
    if len(digits) < 7 or len(digits) > 15:
        return candidate
    return "[PHONE]"


def _redact_cc_safely(match: re.Match[str]) -> str:
    candidate = match.group(0)
    if _luhn_valid(candidate):
        return "[CREDIT_CARD]"
    return candidate


def redact_text(text: str, deny_terms: list[str] | None = None) -> tuple[str, int]:
    """Return (redacted_text, num_redactions)."""
    count = 0

    def _count_sub(pattern: re.Pattern[str], replacement: str | str, source: str) -> str:
        nonlocal count
        new_text, n = pattern.subn(replacement, source)
        count += n
        return new_text

    def _count_func(pattern: re.Pattern[str], func, source: str) -> str:
        nonlocal count
        before = source
        new_text = pattern.sub(func, source)
        count += sum(1 for _ in pattern.finditer(before)) if new_text != before else 0
        return new_text

    text = _count_sub(_EMAIL_RE, "[EMAIL]", text)
    text = _count_sub(_SSN_RE, "[SSN]", text)
    text = _count_sub(_API_KEY_RE, "[API_KEY]", text)
    text = _count_sub(_IPV4_RE, "[IP]", text)
    text = _count_func(_CC_RE, _redact_cc_safely, text)
    text = _count_func(_PHONE_RE, _redact_phone_safely, text)

    if deny_terms:
        for term in deny_terms:
            if not term:
                continue
            pat = re.compile(rf"\b{re.escape(term)}\b", flags=re.IGNORECASE)
            text, n = pat.subn("[REDACTED]", text)
            count += n

    return text, count


def redact_record(record: dict[str, Any], deny_terms: list[str] | None) -> dict[str, Any]:
    total = 0
    if "messages" in record:
        new_messages = []
        for msg in record["messages"]:
            content = msg.get("content", "") or ""
            new_content, n = redact_text(content, deny_terms)
            total += n
            new_messages.append({**msg, "content": new_content})
        record["messages"] = new_messages
    for field in ("prompt", "chosen", "rejected"):
        if field in record and isinstance(record[field], str):
            new_val, n = redact_text(record[field], deny_terms)
            total += n
            record[field] = new_val
    if total > 0:
        record["contains_pii"] = True
    return record


def redact(cfg: dict[str, Any]) -> Path:
    interim = Path(cfg["paths"]["interim"])
    output = Path(cfg["paths"]["redacted"])
    deny_terms = cfg.get("pii", {}).get("deny_terms", [])

    n_in = 0
    n_redacted = 0

    def _stream() -> Iterator[dict[str, Any]]:
        nonlocal n_in, n_redacted
        for record in read_jsonl(interim):
            n_in += 1
            before_pii = bool(record.get("contains_pii"))
            new_record = redact_record(dict(record), deny_terms)
            if new_record.get("contains_pii") and not before_pii:
                n_redacted += 1
            yield new_record

    n_out = write_jsonl(output, _stream())
    log.info(
        "PII redaction complete: %d in / %d out / %d records had new redactions",
        n_in,
        n_out,
        n_redacted,
    )
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Redact PII from interim dataset.")
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    cfg = load_yaml(args.config)
    redact(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
