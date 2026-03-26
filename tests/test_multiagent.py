import json
import tempfile
from pathlib import Path
from storage.sqlite_fts import SqliteFtsStore
from core.indexer import Indexer
from core.search import SearchEngine

CLAUDE_LINES = [
    {
        "type": "user",
        "message": {"role": "user", "content": "deploy docker on hetzner"},
        "sessionId": "claude-s1", "cwd": "/Users/test/Github/headquarters",
        "timestamp": "2026-03-25T10:00:00.000Z", "uuid": "u1"
    },
    {
        "type": "assistant",
        "message": {"role": "assistant", "content": [
            {"type": "text", "text": "Docker deployed on Hetzner."}
        ]},
        "sessionId": "claude-s1", "cwd": "/Users/test/Github/headquarters",
        "timestamp": "2026-03-25T10:00:01.000Z", "uuid": "u2"
    },
]

CODEX_LINES = [
    {
        "timestamp": "2026-03-25T11:00:00.000Z",
        "type": "session_meta",
        "payload": {
            "id": "codex-s1",
            "cwd": "/Users/test/Github/ai-corporation-kfs",
        }
    },
    {
        "timestamp": "2026-03-25T11:00:01.000Z",
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "developer",
            "content": [{"type": "input_text", "text": "fix docker compose config"}]
        }
    },
    {
        "timestamp": "2026-03-25T11:00:02.000Z",
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "Fixed docker-compose.yml ports."}]
        }
    },
]


def test_multiagent_index_and_filter():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        # Claude logs
        claude_dir = tmp_path / "claude_logs" / "-Users-test-Github-headquarters"
        claude_dir.mkdir(parents=True)
        with open(claude_dir / "claude-s1.jsonl", "w") as f:
            for line in CLAUDE_LINES:
                f.write(json.dumps(line) + "\n")

        # Codex logs
        codex_dir = tmp_path / "codex_logs" / "2026" / "03" / "25"
        codex_dir.mkdir(parents=True)
        with open(codex_dir / "rollout-2026-03-25T11-00-codex-s1.jsonl", "w") as f:
            for line in CODEX_LINES:
                f.write(json.dumps(line) + "\n")

        # Setup
        store = SqliteFtsStore(tmp_path / "db" / "sessions.db")
        store.init_db()

        from parsers.codex import CodexParser
        indexer = Indexer(store=store, claude_logs_base=claude_dir.parent)
        # Replace codex parser with custom base path
        indexer.parsers = [p for p in indexer.parsers if p.agent_type != "codex"]
        indexer.parsers.append(CodexParser(logs_base=codex_dir.parent.parent.parent))

        stats = indexer.index_full()
        assert stats["entries_added"] >= 4

        # Search all
        engine = SearchEngine(store=store)
        all_results = engine.search("docker", mode="keyword")
        assert len(all_results) >= 2

        # Filter by agent
        claude_only = engine.search("docker", mode="keyword", agent_type="claude")
        assert all(f.match.agent_type == "claude" for f in claude_only)

        codex_only = engine.search("docker", mode="keyword", agent_type="codex")
        assert all(f.match.agent_type == "codex" for f in codex_only)

        # Stats should show both agents
        s = store.stats()
        assert "claude" in s["by_agent"]
        assert "codex" in s["by_agent"]

        store.close()
