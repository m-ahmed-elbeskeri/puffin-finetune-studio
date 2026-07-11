"""Pure-Python rubric-style judges (no external LLM required).

For richer LLM-as-judge scoring, plug a `Generator` into `llm_judge_score()`.
"""
from __future__ import annotations

import json
import re
from typing import Any

_REFUSAL_PATTERNS = [
    r"\bI can'?t\b",
    r"\bI cannot\b",
    r"\bI'?m unable to\b",
    r"\bI'?m not able to\b",
    r"\bI won'?t\b",
    r"\bSorry,? (?:but )?I (?:can'?t|cannot|won'?t)\b",
    r"\bI'?m (?:sorry|afraid)(?:,| but)? I (?:can'?t|cannot)\b",
]
_REFUSAL_RE = re.compile("|".join(_REFUSAL_PATTERNS), flags=re.IGNORECASE)


def is_refusal(text: str) -> bool:
    """Heuristic: did the model refuse to answer?"""
    return bool(_REFUSAL_RE.search(text or ""))


def is_valid_json(text: str) -> bool:
    """Loose: strip common code-fence wrappers, then parse."""
    if not text:
        return False
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```\s*$", "", cleaned)
    try:
        json.loads(cleaned)
    except (ValueError, TypeError):
        return False
    return True


def contains_keywords(text: str, keywords: list[str], *, all_required: bool = True) -> bool:
    """Check if text contains all (or any) of the keywords (case-insensitive)."""
    if not keywords:
        return True
    text_lower = (text or "").lower()
    matches = [kw.lower() in text_lower for kw in keywords]
    return all(matches) if all_required else any(matches)


def avoids_keywords(text: str, banned: list[str]) -> bool:
    """True if text contains none of the banned keywords (case-insensitive)."""
    if not banned:
        return True
    text_lower = (text or "").lower()
    return not any(kw.lower() in text_lower for kw in banned)


def rubric_score(response: str, criteria: dict[str, Any]) -> dict[str, Any]:
    """Score a single response against a small rubric.

    Criteria keys (all optional):
      - must_contain: list[str]   → all must appear (substring, case-insensitive)
      - must_not_contain: list[str] → none may appear
      - require_json: bool         → output must be valid JSON
      - require_refusal: bool      → output must be a refusal
      - forbid_refusal: bool       → output must NOT be a refusal
      - min_length / max_length: int

    Returns {"pass": bool, "checks": {...detail per check...}}.
    """
    checks: dict[str, bool] = {}
    if "must_contain" in criteria:
        checks["must_contain"] = contains_keywords(response, criteria["must_contain"])
    if "must_not_contain" in criteria:
        checks["must_not_contain"] = avoids_keywords(response, criteria["must_not_contain"])
    if criteria.get("require_json"):
        checks["valid_json"] = is_valid_json(response)
    if criteria.get("require_refusal"):
        checks["is_refusal"] = is_refusal(response)
    if criteria.get("forbid_refusal"):
        checks["not_refusal"] = not is_refusal(response)
    if "min_length" in criteria:
        checks["min_length"] = len(response or "") >= int(criteria["min_length"])
    if "max_length" in criteria:
        checks["max_length"] = len(response or "") <= int(criteria["max_length"])
    return {"pass": all(checks.values()) if checks else True, "checks": checks}


def llm_judge_score(
    response: str,
    rubric_prompt: str,
    judge_generator: Any,
) -> dict[str, Any]:
    """Use a Generator as an LLM judge. Expects a JSON `{"score": 0..1}` output."""
    from llmops.features.schemas import Message, Role

    messages = [
        Message(role=Role.SYSTEM, content="You are a strict evaluation judge. Reply with JSON only."),
        Message(role=Role.USER, content=rubric_prompt + "\n\nResponse to score:\n" + response),
    ]
    out = judge_generator.generate(messages, max_new_tokens=64)
    try:
        parsed = json.loads(out.text)
        score = float(parsed.get("score", 0.0))
    except (ValueError, TypeError, KeyError):
        score = 0.0
    return {"score": score, "raw": out.text}
