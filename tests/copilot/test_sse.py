"""SSE encode/parse round-trip."""
from copilot.backend.sse import encode_sse, parse_sse


def test_round_trip_text():
    raw = encode_sse("text", {"text": "hello world"})
    parsed = parse_sse(raw)
    assert parsed == [("text", {"text": "hello world"})]


def test_round_trip_multiple():
    parts = b""
    parts += encode_sse("a", {"x": 1})
    parts += encode_sse("b", {"y": [1, 2, 3]})
    parts += encode_sse("c", {"nested": {"k": "v"}})
    parsed = parse_sse(parts)
    assert parsed == [
        ("a", {"x": 1}),
        ("b", {"y": [1, 2, 3]}),
        ("c", {"nested": {"k": "v"}}),
    ]


def test_handles_unicode():
    raw = encode_sse("text", {"text": "→ 🎉 café"})
    parsed = parse_sse(raw)
    assert parsed[0][1]["text"] == "→ 🎉 café"
