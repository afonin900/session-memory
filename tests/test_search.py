# tests/test_search.py
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from storage.sqlite_fts import SqliteFtsStore
from storage.models import LogEntry
from core.search import SearchEngine


def _make_store_with_data(tmp_path: Path) -> SqliteFtsStore:
    store = SqliteFtsStore(tmp_path / "test.db")
    store.init_db()
    entries = [
        LogEntry("claude", "hq", "s1", "user", "deploy docker on hetzner",
                 datetime(2026, 3, 25, 10, 0, 0, tzinfo=timezone.utc),
                 [], [], "/tmp/a.jsonl"),
        LogEntry("claude", "hq", "s1", "assistant", "Running docker compose on Hetzner VPS",
                 datetime(2026, 3, 25, 10, 0, 1, tzinfo=timezone.utc),
                 ["/refs/infra.md"], ["84"], "/tmp/a.jsonl"),
        LogEntry("claude", "kfs", "s2", "user", "mining pipeline broken",
                 datetime(2026, 3, 25, 11, 0, 0, tzinfo=timezone.utc),
                 [], [], "/tmp/b.jsonl"),
        LogEntry("claude", "kfs", "s2", "assistant", "Fixing pipeline transcription error",
                 datetime(2026, 3, 25, 11, 0, 1, tzinfo=timezone.utc),
                 [], [], "/tmp/b.jsonl"),
    ]
    store.insert_entries(entries)
    return store


def test_keyword_search():
    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store_with_data(Path(tmp))
        engine = SearchEngine(store=store)
        fragments = engine.search("docker", mode="keyword")
        assert len(fragments) >= 1
        assert any("docker" in f.match.content.lower() for f in fragments)
        store.close()


def test_keyword_search_with_context():
    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store_with_data(Path(tmp))
        engine = SearchEngine(store=store)
        fragments = engine.search("docker compose", mode="keyword")
        assert len(fragments) >= 1
        # Context window should include surrounding messages
        frag = fragments[0]
        assert frag.session_id == "s1"
        store.close()


def test_search_with_filters():
    with tempfile.TemporaryDirectory() as tmp:
        store = _make_store_with_data(Path(tmp))
        engine = SearchEngine(store=store)
        fragments = engine.search("pipeline", mode="keyword", project="kfs")
        assert len(fragments) >= 1
        assert all(f.project == "kfs" for f in fragments)
        store.close()
