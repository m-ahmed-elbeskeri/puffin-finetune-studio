from __future__ import annotations

from llmops.data.redact_pii import _luhn_valid, redact_record, redact_text


def test_email_redacted():
    out, n = redact_text("ping me at alice@example.com please")
    assert "[EMAIL]" in out
    assert "alice@example.com" not in out
    assert n == 1


def test_phone_redacted():
    out, n = redact_text("call (415) 555-0199 anytime")
    assert "[PHONE]" in out
    assert "555" not in out
    assert n >= 1


def test_ssn_redacted():
    out, n = redact_text("SSN 123-45-6789 here")
    assert "[SSN]" in out
    assert "123-45-6789" not in out
    assert n == 1


def test_credit_card_redacted_with_luhn():
    # 4111 1111 1111 1111 is a Luhn-valid test number
    out, n = redact_text("card 4111 1111 1111 1111 expires soon")
    assert "[CREDIT_CARD]" in out
    assert n == 1


def test_credit_card_invalid_luhn_kept():
    # 1234 5678 9012 3456 is NOT Luhn-valid
    out, _ = redact_text("not-a-card 1234 5678 9012 3456")
    assert "[CREDIT_CARD]" not in out


def test_ipv4_redacted():
    out, n = redact_text("from 192.168.1.50 inbound")
    assert "[IP]" in out
    assert n == 1


def test_api_keys_redacted():
    out, n = redact_text("OPENAI_KEY=sk-1234567890ABCDEFGHIJKLMNOPQRSTUV")
    assert "[API_KEY]" in out
    assert n == 1


def test_ghp_token_redacted():
    out, n = redact_text("token=ghp_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
    assert "[API_KEY]" in out
    assert n == 1


def test_deny_terms():
    out, n = redact_text("project Codename Falcon details", deny_terms=["Falcon"])
    assert "[REDACTED]" in out
    assert "Falcon" not in out
    assert n == 1


def test_redact_record_marks_pii():
    rec = {
        "id": "1",
        "messages": [
            {"role": "user", "content": "email me at bob@corp.com"},
            {"role": "assistant", "content": "ok"},
        ],
    }
    out = redact_record(rec, deny_terms=None)
    assert out["contains_pii"] is True
    assert "[EMAIL]" in out["messages"][0]["content"]


def test_redact_record_preference_fields():
    rec = {"prompt": "email alice@x.com", "chosen": "ok", "rejected": "no"}
    out = redact_record(rec, deny_terms=None)
    assert "[EMAIL]" in out["prompt"]


def test_luhn_helper():
    assert _luhn_valid("4111 1111 1111 1111") is True
    assert _luhn_valid("1234567890123456") is False
