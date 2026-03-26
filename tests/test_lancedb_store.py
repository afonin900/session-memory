# tests/test_lancedb_store.py
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from storage.lancedb_store import LanceDBStore
from storage.models import LogEntry
from core.embedder import Embedder


def _make_entry(content: str, **kwargs) -> LogEntry:
    defaults = dict(
        agent_type="claude", project="hq", session_id="s1",
        role="assistant", content=content,
        timestamp=datetime(2026, 3, 25, 10, 0, 0, tzinfo=timezone.utc),
        file_paths=[], issue_numbers=[], source_file="/tmp/test.jsonl",
    )
    defaults.update(kwargs)
    return LogEntry(**defaults)


def test_insert_and_search():
    with tempfile.TemporaryDirectory() as tmp:
        store = LanceDBStore(Path(tmp) / "vectors", Embedder())
        store.init_db()
        entries = [
            _make_entry("деплой docker на hetzner сервер"),
            _make_entry("настройка nginx reverse proxy"),
            _make_entry("рецепт приготовления борща"),
        ]
        store.insert_entries(entries, ids=[1, 2, 3])
        results = store.search("установка докера на VPS")
        assert len(results) >= 1
        assert "docker" in results[0].content.lower() or "docker" in results[0].content


def test_search_with_project_filter():
    with tempfile.TemporaryDirectory() as tmp:
        store = LanceDBStore(Path(tmp) / "vectors", Embedder())
        store.init_db()
        store.insert_entries([
            _make_entry("docker deploy", project="hq"),
            _make_entry("docker compose", project="kfs"),
        ], ids=[1, 2])
        results = store.search("docker", project="kfs")
        assert all(r.project == "kfs" for r in results)


def test_delete_by_source():
    with tempfile.TemporaryDirectory() as tmp:
        store = LanceDBStore(Path(tmp) / "vectors", Embedder())
        store.init_db()
        store.insert_entries([
            _make_entry("test content", source_file="/tmp/a.jsonl"),
        ], ids=[1])
        store.delete_by_source("/tmp/a.jsonl")
        results = store.search("test content")
        assert len(results) == 0
