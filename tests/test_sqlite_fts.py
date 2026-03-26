# tests/test_sqlite_fts.py
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from storage.sqlite_fts import SqliteFtsStore
from storage.models import LogEntry


def _make_entry(**kwargs) -> LogEntry:
    defaults = dict(
        agent_type="claude",
        project="hq",
        session_id="sess-001",
        role="assistant",
        content="default content",
        timestamp=datetime(2026, 3, 25, 10, 0, 0, tzinfo=timezone.utc),
        file_paths=[],
        issue_numbers=[],
        source_file="/tmp/test.jsonl",
    )
    defaults.update(kwargs)
    return LogEntry(**defaults)


def test_init_creates_tables():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        store = SqliteFtsStore(db_path)
        store.init_db()
        # Should not raise, tables exist
        rows = store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = [r[0] for r in rows]
        assert "sessions_log" in table_names
        assert "sessions_fts" in table_names
        assert "indexed_files" in table_names
        store.close()


def test_insert_and_search():
    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteFtsStore(Path(tmp) / "test.db")
        store.init_db()
        entries = [
            _make_entry(content="деплой docker на hetzner VPS"),
            _make_entry(content="настройка nginx reverse proxy"),
            _make_entry(content="создание telegram бота"),
        ]
        store.insert_entries(entries)
        results = store.search("docker hetzner")
        assert len(results) >= 1
        assert "docker" in results[0].content
        store.close()


def test_search_with_project_filter():
    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteFtsStore(Path(tmp) / "test.db")
        store.init_db()
        store.insert_entries([
            _make_entry(content="docker deploy", project="hq"),
            _make_entry(content="docker compose", project="kfs"),
        ])
        results = store.search("docker", project="kfs")
        assert len(results) == 1
        assert results[0].project == "kfs"
        store.close()


def test_search_with_days_filter():
    from datetime import timedelta
    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteFtsStore(Path(tmp) / "test.db")
        store.init_db()
        now = datetime.now(timezone.utc)
        store.insert_entries([
            _make_entry(
                content="old docker deploy",
                timestamp=now - timedelta(days=60),
            ),
            _make_entry(
                content="new docker deploy",
                timestamp=now - timedelta(hours=1),
            ),
        ])
        results = store.search("docker", days=30)
        assert len(results) == 1
        assert "new" in results[0].content
        store.close()


def test_indexed_files_tracking():
    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteFtsStore(Path(tmp) / "test.db")
        store.init_db()
        store.mark_indexed("/tmp/a.jsonl", 1000.0, 5)
        assert store.is_indexed("/tmp/a.jsonl", 1000.0)
        assert not store.is_indexed("/tmp/a.jsonl", 2000.0)  # mtime changed
        assert not store.is_indexed("/tmp/b.jsonl", 1000.0)  # different file
        store.close()


def test_get_context_window():
    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteFtsStore(Path(tmp) / "test.db")
        store.init_db()
        entries = [
            _make_entry(content="first message", role="user",
                        timestamp=datetime(2026, 3, 25, 10, 0, i, tzinfo=timezone.utc))
            for i in range(5)
        ]
        entries[0].content = "message zero"
        entries[1].content = "message one"
        entries[2].content = "target message"
        entries[3].content = "message three"
        entries[4].content = "message four"
        ids = store.insert_entries(entries)
        fragment = store.get_context(ids[2], window=2)
        assert fragment.match.content == "target message"
        assert len(fragment.before) == 2
        assert len(fragment.after) == 2
        assert fragment.before[0].content == "message zero"
        store.close()


def test_stats():
    with tempfile.TemporaryDirectory() as tmp:
        store = SqliteFtsStore(Path(tmp) / "test.db")
        store.init_db()
        store.insert_entries([
            _make_entry(project="hq", agent_type="claude"),
            _make_entry(project="kfs", agent_type="claude"),
            _make_entry(project="kfs", agent_type="codex"),
        ])
        stats = store.stats()
        assert stats["total"] == 3
        assert stats["by_project"]["kfs"] == 2
        assert stats["by_agent"]["claude"] == 2
        store.close()
