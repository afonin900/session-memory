# core/llm.py — LLM abstraction via OpenRouter API
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "anthropic/claude-3.5-haiku"


def _get_api_key() -> str | None:
    """Get OpenRouter API key from env or .env file."""
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        return key

    # Fallback: read from KFS .env
    env_path = Path.home() / "Github" / "ai-corporation-kfs" / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("OPENROUTER_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")

    return None


def call_llm(
    prompt: str,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 2000,
    temperature: float = 0.3,
) -> str | None:
    """Call LLM via OpenRouter API.

    Returns response text or None on failure.
    """
    api_key = _get_api_key()
    if not api_key:
        return None

    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }).encode("utf-8")

    req = Request(
        OPENROUTER_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/afonin900/session-memory",
        },
    )

    try:
        with urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
    except (URLError, HTTPError, KeyError, json.JSONDecodeError, TimeoutError) as e:
        print(f"LLM call failed: {e}")
        return None
