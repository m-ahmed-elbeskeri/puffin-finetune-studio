from __future__ import annotations

from llmops.serving.postprocess import strip_code_fences, truncate_at_stop


def test_strip_code_fences_json():
    assert strip_code_fences('```json\n{"a":1}\n```') == '{"a":1}'


def test_strip_code_fences_no_fence():
    assert strip_code_fences("plain text") == "plain text"


def test_strip_code_fences_unlabeled():
    assert strip_code_fences("```\n{\"a\":1}\n```") == '{"a":1}'


def test_truncate_at_stop():
    assert truncate_at_stop("hello world END more", ["END"]) == "hello world "


def test_truncate_at_first_stop():
    assert truncate_at_stop("ABCSTOPDEF", ["DEF", "STOP"]) == "ABC"


def test_truncate_no_match():
    assert truncate_at_stop("abc", ["xyz"]) == "abc"


def test_truncate_empty_stop_list():
    assert truncate_at_stop("abc", []) == "abc"
    assert truncate_at_stop("abc", None) == "abc"
