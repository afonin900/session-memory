# tests/test_cli.py
import json
import subprocess
import sys
import tempfile
from pathlib import Path

CLI = str(Path(__file__).parent.parent / "cli.py")

SAMPLE_LINES = [
    {
        "type": "user",
        "message": {"role": "user", "content": "deploy docker on hetzner"},
        "sessionId": "s1", "cwd": "/Users/test/Github/headquarters",
        "timestamp": "2026-03-25T10:00:00.000Z", "uuid": "u1"
    },
    {
        "type": "assistant",
        "message": {"role": "assistant", "content": [
            {"type": "text", "text": "Docker compose up on Hetzner VPS."}
        ]},
        "sessionId": "s1", "cwd": "/Users/test/Github/headquarters",
        "timestamp": "2026-03-25T10:00:01.000Z", "uuid": "u2"
    },
]


def _setup(tmp: Path) -> dict:
    logs = tmp / "logs" / "-Users-test-Github-headquarters"
    logs.mkdir(parents=True)
    jsonl = logs / "s1.jsonl"
    with open(jsonl, "w") as f:
        for line in SAMPLE_LINES:
            f.write(json.dumps(line) + "\n")
    db_dir = tmp / "db"
    return {"SM_DB_DIR": str(db_dir), "SM_CLAUDE_LOGS": str(logs.parent)}


def test_cli_index():
    with tempfile.TemporaryDirectory() as tmp:
        env_vars = _setup(Path(tmp))
        result = subprocess.run(
            [sys.executable, CLI, "index"],
            capture_output=True, text=True,
            env={**dict(__import__("os").environ), **env_vars},
        )
        assert result.returncode == 0
        assert "files_indexed" in result.stdout or "Indexed" in result.stdout


def test_cli_search():
    with tempfile.TemporaryDirectory() as tmp:
        env_vars = _setup(Path(tmp))
        env = {**dict(__import__("os").environ), **env_vars}
        # First index
        subprocess.run([sys.executable, CLI, "index"], env=env, capture_output=True)
        # Then search
        result = subprocess.run(
            [sys.executable, CLI, "search", "docker"],
            capture_output=True, text=True, env=env,
        )
        assert result.returncode == 0
        assert "docker" in result.stdout.lower()


def test_cli_stats():
    with tempfile.TemporaryDirectory() as tmp:
        env_vars = _setup(Path(tmp))
        env = {**dict(__import__("os").environ), **env_vars}
        subprocess.run([sys.executable, CLI, "index"], env=env, capture_output=True)
        result = subprocess.run(
            [sys.executable, CLI, "stats"],
            capture_output=True, text=True, env=env,
        )
        assert result.returncode == 0
        assert "total" in result.stdout.lower() or "Total" in result.stdout
