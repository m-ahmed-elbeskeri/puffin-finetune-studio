from __future__ import annotations

from llmops.evaluation.runner import EchoGenerator, build_generator
from llmops.features.schemas import Message, Role


def test_echo_default_response():
    gen = EchoGenerator(rules=[], default_response="DEFAULT")
    out = gen.generate([Message(role=Role.USER, content="hi")])
    assert out.text == "DEFAULT"
    assert out.input_tokens > 0


def test_echo_pattern_match_first_wins():
    gen = EchoGenerator(
        rules=[
            ("password", "RESET_INSTRUCTIONS"),
            (".*", "FALLBACK"),
        ],
        default_response="DEFAULT",
    )
    out = gen.generate([Message(role=Role.USER, content="my password")])
    assert out.text == "RESET_INSTRUCTIONS"


def test_echo_case_insensitive():
    gen = EchoGenerator(rules=[("password", "OK")], default_response="X")
    out = gen.generate([Message(role=Role.USER, content="My PASSWORD")])
    assert out.text == "OK"


def test_build_generator_echo():
    cfg = {
        "backend": "echo",
        "echo_default": "X",
        "echo_rules": [{"pattern": "p", "response": "Q"}],
    }
    gen = build_generator(cfg)
    assert gen.backend == "echo"
    out = gen.generate([Message(role=Role.USER, content="please p")])
    assert out.text == "Q"
