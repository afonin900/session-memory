import fcntl
import json
import os
import tempfile
import time
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
        assert stats["files_indexed"] >= 1
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


# --- Task 1: _should_skip_file ---

def test_should_skip_recent_file(tmp_path):
    """Files modified within skip_recent_minutes should be skipped."""
    from core.indexer import Indexer
    from storage.sqlite_fts import SqliteFtsStore

    db_path = tmp_path / "db" / "sessions.db"
    store = SqliteFtsStore(db_path)
    store.init_db()
    indexer = Indexer(store=store)

    recent_file = tmp_path / "recent.jsonl"
    recent_file.write_text("{}")
    assert indexer._should_skip_file(recent_file, skip_recent_minutes=60) is True

    old_file = tmp_path / "old.jsonl"
    old_file.write_text("{}")
    old_mtime = time.time() - 7200
    os.utime(old_file, (old_mtime, old_mtime))
    assert indexer._should_skip_file(old_file, skip_recent_minutes=60) is False

    store.close()


# --- Task 2: index_fts_only ---

def test_index_fts_only_indexes_old_files():
    """FTS-only mode should index files older than skip_recent_minutes."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        logs_base, db_path = _setup_env(tmp_path)

        jsonl = logs_base / "-Users-test-Github-headquarters" / "sess-001.jsonl"
        old_mtime = time.time() - 7200
        os.utime(jsonl, (old_mtime, old_mtime))

        store = SqliteFtsStore(db_path)
        store.init_db()
        indexer = Indexer(store=store, claude_logs_base=logs_base)

        stats = indexer.index_fts_only(skip_recent_minutes=60)
        assert stats["files_indexed"] >= 1
        assert stats["entries_added"] >= 2

        results = store.search("docker")
        assert len(results) >= 1
        store.close()


def test_index_fts_only_skips_recent_files():
    """FTS-only mode should skip files modified within skip_recent_minutes."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        logs_base, db_path = _setup_env(tmp_path)

        store = SqliteFtsStore(db_path)
        store.init_db()
        indexer = Indexer(store=store, claude_logs_base=logs_base)

        stats = indexer.index_fts_only(skip_recent_minutes=60)
        # The test file was just written (recent) — it must be skipped
        assert stats["files_skipped_recent"] >= 1
        # Verify the test session file specifically was NOT indexed (search returns nothing for test-only data)
        results = store.search("docker")
        assert len(results) == 0
        store.close()


# --- Task 3: index_vectors_bg ---

def test_index_vectors_bg_no_vector_store():
    """vectors-bg without vector store should return no_vector_store."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        logs_base, db_path = _setup_env(tmp_path)

        store = SqliteFtsStore(db_path)
        store.init_db()
        indexer = Indexer(store=store, claude_logs_base=logs_base)

        lock_path = str(tmp_path / "vectors.lock")
        result = indexer.index_vectors_bg(lock_path=lock_path, skip_recent_minutes=60)
        assert result["status"] == "no_vector_store"
        store.close()


def test_index_vectors_bg_skips_when_locked():
    """vectors-bg should exit silently if lock is already held."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        logs_base, db_path = _setup_env(tmp_path)

        store = SqliteFtsStore(db_path)
        store.init_db()
        indexer = Indexer(store=store, claude_logs_base=logs_base)
        indexer.vector_store = True  # fake, so it reaches lock check

        lock_path = str(tmp_path / "vectors.lock")
        lock_file = open(lock_path, "w")
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = indexer.index_vectors_bg(lock_path=lock_path, skip_recent_minutes=60)
            assert result["status"] == "locked"
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)
            lock_file.close()

        store.close()
