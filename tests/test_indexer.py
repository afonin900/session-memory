import json
import tempfile
from pathlib import Path
from core.indexer import Indexer
from storage.sqlite_fts import SqliteFtsStore

SAMPLE_LINES = [
    {
        "type": "user",
        "message": {"role": "user", "content": "deploy docker"},
        "sessionId": "sess-001",
        "cwd": "/Users/test/Github/headquarters",
        "timestamp": "2026-03-25T10:00:00.000Z",
        "uuid": "u1"
    },
    {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": "Running docker compose up."}],
        },
        "sessionId": "sess-001",
        "cwd": "/Users/test/Github/headquarters",
        "timestamp": "2026-03-25T10:00:01.000Z",
        "uuid": "u2"
    },
]


def _setup_env(tmp_path: Path) -> tuple[Path, Path]:
    logs_dir = tmp_path / "logs" / "-Users-test-Github-headquarters"
    logs_dir.mkdir(parents=True)
    jsonl = logs_dir / "sess-001.jsonl"
    with open(jsonl, "w") as f:
        for line in SAMPLE_LINES:
            f.write(json.dumps(line) + "\n")
    db_path = tmp_path / "db" / "sessions.db"
    return logs_dir.parent, db_path


def test_index_full():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        logs_base, db_path = _setup_env(tmp_path)

        store = SqliteFtsStore(db_path)
        store.init_db()

        indexer = Indexer(store=store, claude_logs_base=logs_base)
        stats = indexer.index_full()
        assert stats["files_indexed"] == 1
        assert stats["entries_added"] >= 2

        # Search should work
        results = store.search("docker")
        assert len(results) >= 1
        store.close()


def test_index_incremental_skips_unchanged():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        logs_base, db_path = _setup_env(tmp_path)

        store = SqliteFtsStore(db_path)
        store.init_db()

        indexer = Indexer(store=store, claude_logs_base=logs_base)
        indexer.index_full()

        # Second run should skip everything
        stats = indexer.index_incremental()
        assert stats["files_indexed"] == 0
        assert stats["files_skipped"] >= 1
        store.close()


def test_index_incremental_reindexes_changed():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        logs_base, db_path = _setup_env(tmp_path)

        store = SqliteFtsStore(db_path)
        store.init_db()

        indexer = Indexer(store=store, claude_logs_base=logs_base)
        indexer.index_full()

        # Modify the file (append a line)
        jsonl = logs_base / "-Users-test-Github-headquarters" / "sess-001.jsonl"
        with open(jsonl, "a") as f:
            f.write(json.dumps({
                "type": "user",
                "message": {"role": "user", "content": "new message"},
                "sessionId": "sess-001",
                "cwd": "/Users/test/Github/headquarters",
                "timestamp": "2026-03-25T10:00:02.000Z",
                "uuid": "u3"
            }) + "\n")

        stats = indexer.index_incremental()
        assert stats["files_indexed"] == 1
        store.close()
