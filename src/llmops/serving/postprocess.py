"""Output post-processing helpers."""
from __future__ import annotations

import re

_CODE_FENCE_RE = re.compile(r"^```(?:[a-zA-Z0-9]+)?\s*\n?|\n?\s*```\s*$")


def strip_code_fences(text: str) -> str:
    """Remove surrounding markdown code fences (e.g. ```json ... ```)."""
    cleaned = text.strip()
    cleaned = _CODE_FENCE_RE.sub("", cleaned, count=1)
    cleaned = _CODE_FENCE_RE.sub("", cleaned, count=1)
    return cleaned.strip()


def truncate_at_stop(text: str, stop: list[str] | None) -> str:
    """Truncate at the first occurrence of any stop sequence."""
    if not stop:
        return text
    earliest = len(text)
    for s in stop:
        idx = text.find(s)
        if idx >= 0:
            earliest = min(earliest, idx)
    return text[:earliest]
