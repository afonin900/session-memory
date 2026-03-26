# tests/test_semantic_integration.py
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from storage.sqlite_fts import SqliteFtsStore
from storage.lancedb_store import LanceDBStore
from core.embedder import Embedder
from core.indexer import Indexer
from core.search import SearchEngine

SAMPLE_LINES = [
    {
        "type": "user",
        "message": {"role": "user", "content": "как починить потерю данных при деплое?"},
        "sessionId": "s1", "cwd": "/Users/test/Github/headquarters",
        "timestamp": "2026-03-25T10:00:00.000Z", "uuid": "u1"
    },
    {
        "type": "assistant",
        "message": {"role": "assistant", "content": [
            {"type": "text", "text": "Нужно проверить миграции БД перед docker compose up. Backup обязателен."}
        ]},
        "sessionId": "s1", "cwd": "/Users/test/Github/headquarters",
        "timestamp": "2026-03-25T10:00:01.000Z", "uuid": "u2"
    },
    {
        "type": "user",
        "message": {"role": "user", "content": "рецепт борща с мясом"},
        "sessionId": "s1", "cwd": "/Users/test/Github/headquarters",
        "timestamp": "2026-03-25T10:00:02.000Z", "uuid": "u3"
    },
]


def test_semantic_search_finds_relevant():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        # Setup logs
        logs_dir = tmp_path / "logs" / "-Users-test-Github-headquarters"
        logs_dir.mkdir(parents=True)
        with open(logs_dir / "s1.jsonl", "w") as f:
            for line in SAMPLE_LINES:
                f.write(json.dumps(line) + "\n")

        # Setup stores
        store = SqliteFtsStore(tmp_path / "db" / "sessions.db")
        store.init_db()
        embedder = Embedder()
        vstore = LanceDBStore(tmp_path / "db" / "vectors", embedder)
        vstore.init_db()

        # Index
        indexer = Indexer(store=store, claude_logs_base=logs_dir.parent, vector_store=vstore)
        indexer.index_full()

        # Semantic search — should find data loss / deploy related content, not borsch
        engine = SearchEngine(store=store, vector_store=vstore)
        fragments = engine.search("проблемы с данными при обновлении", mode="semantic")
        assert len(fragments) >= 1
        # The deploy-related content should rank higher than borsch
        assert "борщ" not in fragments[0].match.content.lower()


def test_merged_search():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        logs_dir = tmp_path / "logs" / "-Users-test-Github-headquarters"
        logs_dir.mkdir(parents=True)
        with open(logs_dir / "s1.jsonl", "w") as f:
            for line in SAMPLE_LINES:
                f.write(json.dumps(line) + "\n")

        store = SqliteFtsStore(tmp_path / "db" / "sessions.db")
        store.init_db()
        embedder = Embedder()
        vstore = LanceDBStore(tmp_path / "db" / "vectors", embedder)
        vstore.init_db()

        indexer = Indexer(store=store, claude_logs_base=logs_dir.parent, vector_store=vstore)
        indexer.index_full()

        engine = SearchEngine(store=store, vector_store=vstore)
        fragments = engine.search("миграции", mode="all")
        assert len(fragments) >= 1
