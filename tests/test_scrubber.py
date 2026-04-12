import pytest
from core.scrubber import scrub_secrets


def test_scrub_anthropic_api_key():
    text = "Using key sk-ant-api03-abc123def456ghijklmnop for auth"
    result = scrub_secrets(text)
    assert "sk-ant-api03" not in result
    assert "[REDACTED_API_KEY]" in result


def test_scrub_openrouter_key():
    text = "OPENROUTER_API_KEY=sk-or-v1-abc123def456ghijklmnopqrstuvwxyz"
    result = scrub_secrets(text)
    assert "sk-or-v1" not in result


def test_scrub_jwt():
    text = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
    result = scrub_secrets(text)
    assert "eyJhbGci" not in result
    assert "[REDACTED_JWT]" in result


def test_scrub_aws():
    text = "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
    result = scrub_secrets(text)
    assert "wJalrXUtnFEMI" not in result


def test_scrub_db_url():
    text = 'DATABASE_URL="postgres://user:p@ssw0rd@host:5432/db"'
    result = scrub_secrets(text)
    assert "p@ssw0rd" not in result


def test_scrub_context7_key():
    text = "CONTEXT7_API_KEY=ctx7sk-8dd1269a-eae3-40fa-b3c6-bbbffffd4853"
    result = scrub_secrets(text)
    assert "ctx7sk-" not in result


def test_scrub_preserves_normal_text():
    text = "Normal conversation about code changes and deploy"
    result = scrub_secrets(text)
    assert result == text


def test_scrub_multiple_secrets():
    text = "Key: sk-ant-api03-abc123def456ghijklmnop and JWT: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
    result = scrub_secrets(text)
    assert "[REDACTED_API_KEY]" in result
    assert "[REDACTED_JWT]" in result
    assert "sk-ant" not in result
    assert "eyJhbGci" not in result
