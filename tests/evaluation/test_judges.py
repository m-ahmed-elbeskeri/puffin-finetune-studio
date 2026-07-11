from __future__ import annotations

from llmops.evaluation.judges import (
    avoids_keywords,
    contains_keywords,
    is_refusal,
    is_valid_json,
    rubric_score,
)


def test_is_refusal_positive():
    assert is_refusal("I'm sorry, I can't help with that.")
    assert is_refusal("I cannot do that.")
    assert is_refusal("I won't comply.")


def test_is_refusal_negative():
    assert not is_refusal("Sure, here you go.")
    assert not is_refusal("")


def test_is_valid_json_plain():
    assert is_valid_json('{"a":1}')


def test_is_valid_json_fenced():
    assert is_valid_json('```json\n{"a":1}\n```')


def test_is_valid_json_invalid():
    assert not is_valid_json("not json")
    assert not is_valid_json("")


def test_contains_keywords_all():
    assert contains_keywords("the quick brown fox", ["quick", "fox"])
    assert not contains_keywords("the quick brown fox", ["quick", "panda"])


def test_avoids_keywords():
    assert avoids_keywords("nothing bad here", ["badword"])
    assert not avoids_keywords("contains badword", ["BadWord"])


def test_rubric_score_passes_when_all_checks_satisfied():
    res = rubric_score(
        "Yes, return policy is 30 days.",
        {
            "must_contain": ["30"],
            "must_not_contain": ["60"],
            "min_length": 5,
        },
    )
    assert res["pass"] is True
    assert all(res["checks"].values())


def test_rubric_score_fails_clear_reason():
    res = rubric_score("nope", {"must_contain": ["thirty"]})
    assert res["pass"] is False
    assert res["checks"]["must_contain"] is False


def test_rubric_score_empty_criteria():
    assert rubric_score("anything", {})["pass"] is True
