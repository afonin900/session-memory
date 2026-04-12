# core/scrubber.py — Secret scrubbing for transcripts
import re

_PATTERNS = [
    # API keys (Anthropic, OpenAI, OpenRouter, Context7)
    (r"sk-ant-[a-zA-Z0-9_-]{20,}", "[REDACTED_API_KEY]"),
    (r"sk-or-v1-[a-zA-Z0-9]{20,}", "[REDACTED_API_KEY]"),
    (r"sk-[a-zA-Z0-9]{20,}", "[REDACTED_API_KEY]"),
    (r"ctx7sk-[a-zA-Z0-9-]{20,}", "[REDACTED_API_KEY]"),
    # JWT tokens
    (r"eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}", "[REDACTED_JWT]"),
    # AWS
    (r"AKIA[0-9A-Z]{16}", "[REDACTED_AWS_KEY]"),
    (r"(?:aws_secret_access_key|AWS_SECRET_ACCESS_KEY)\s*=\s*[a-zA-Z0-9/+=]{20,}", "[REDACTED_AWS_SECRET]"),
    # Connection strings with passwords
    (r"(?:postgres|mysql|mongodb)://[^:]+:[^@]+@[^\s\"']+", "[REDACTED_DB_URL]"),
    # Generic KEY=value patterns for sensitive env vars
    (r"(?:API_KEY|SECRET_KEY|PASSWORD|TOKEN|PRIVATE_KEY|OPENROUTER_API_KEY|CONTEXT7_API_KEY)\s*=\s*[\"']?[^\s\"']{8,}[\"']?", "[REDACTED_ENV_VAR]"),
]

_COMPILED = [(re.compile(p, re.IGNORECASE), repl) for p, repl in _PATTERNS]


def scrub_secrets(text: str) -> str:
    """Remove secrets from text using regex patterns."""
    for pattern, replacement in _COMPILED:
        text = pattern.sub(replacement, text)
    return text
