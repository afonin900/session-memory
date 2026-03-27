# storage/lancedb_store.py
import gc
import lancedb
import pyarrow as pa
from datetime import datetime, timezone, timedelta
from pathlib import Path

from core.embedder import Embedder
from storage.models import LogEntry, SearchResult
from config import EMBEDDING_DIM

TABLE_NAME = "sessions_vectors"

_SCHEMA = pa.schema([
    pa.field("id", pa.int64()),
    pa.field("text", pa.string()),
    pa.field("vector", pa.list_(pa.float32(), EMBEDDING_DIM)),
    pa.field("agent_type", pa.string()),
    pa.field("project", pa.string()),
    pa.field("session_id", pa.string()),
    pa.field("role", pa.string()),
    pa.field("timestamp", pa.string()),
    pa.field("source_file", pa.string()),
])


class LanceDBStore:
    def __init__(self, vectors_dir: Path, embedder: Embedder):
        self.vectors_dir = vectors_dir
        self.embedder = embedder
        self._db = None

    def init_db(self):
        self.vectors_dir.mkdir(parents=True, exist_ok=True)
        self._db = lancedb.connect(str(self.vectors_dir))
        # Create table if not exists
        existing = self._db.list_tables()
        existing_names = existing.tables if hasattr(existing, "tables") else list(existing)
        if TABLE_NAME not in existing_names:
            self._db.create_table(TABLE_NAME, schema=_SCHEMA)

    def reconnect(self):
        """Drop and reopen LanceDB connection to flush Arrow memory pools."""
        self._db = None
        gc.collect()
        pa.default_memory_pool().release_unused()
        self._db = lancedb.connect(str(self.vectors_dir))

    def drop_table(self):
        """Drop vector table completely. Use before bulk reindex to avoid fragmentation."""
        existing = self._db.list_tables()
        existing_names = existing.tables if hasattr(existing, "tables") else list(existing)
        if TABLE_NAME in existing_names:
            self._db.drop_table(TABLE_NAME)
        self._db.create_table(TABLE_NAME, schema=_SCHEMA)

    def _get_table(self):
        return self._db.open_table(TABLE_NAME)

    def insert_entries(self, entries: list[LogEntry], ids: list[int], chunk_size: int = 250):
        """Insert entries with pre-assigned IDs from SQLite. Processes in chunks to limit memory.

        Uses pyarrow Table directly instead of list[dict] to avoid x7 memory overhead
        from numpy float32 -> Python list[float] conversion via .tolist().
        """
        if not entries:
            return

        table = self._get_table()

        for start in range(0, len(entries), chunk_size):
            chunk_entries = entries[start:start + chunk_size]
            chunk_ids = ids[start:start + chunk_size]

            texts = [e.content for e in chunk_entries]
            vectors = self.embedder.embed_passages(texts)  # shape: (N, DIM), float32 numpy

            # Build pyarrow arrays directly — avoids .tolist() float32->float64 overhead
            vectors_array = pa.FixedSizeListArray.from_arrays(
                pa.array(vectors.flatten(), type=pa.float32()),
                list_size=vectors.shape[1],
            )

            batch = pa.table({
                "id": pa.array(chunk_ids, type=pa.int64()),
                "text": pa.array(texts, type=pa.string()),
                "vector": vectors_array,
                "agent_type": pa.array([e.agent_type for e in chunk_entries], type=pa.string()),
                "project": pa.array([e.project for e in chunk_entries], type=pa.string()),
                "session_id": pa.array([e.session_id for e in chunk_entries], type=pa.string()),
                "role": pa.array([e.role for e in chunk_entries], type=pa.string()),
                "timestamp": pa.array([e.timestamp.isoformat() for e in chunk_entries], type=pa.string()),
                "source_file": pa.array([e.source_file for e in chunk_entries], type=pa.string()),
            })

            table.add(batch)
            del vectors, batch, vectors_array

    def search(
        self,
        query: str,
        project: str | None = None,
        agent_type: str | None = None,
        days: int | None = None,
        role: str | None = None,
        limit: int = 20,
    ) -> list[SearchResult]:
        """Semantic search using vector similarity."""
        query_vec = self.embedder.embed_query(query)
        table = self._get_table()

        search_query = table.search(query_vec.tolist())

        # Build filter (escape quotes to prevent injection)
        def _esc(v: str) -> str:
            return v.replace("'", "''")

        filters = []
        if project:
            filters.append(f"project = '{_esc(project)}'")
        if agent_type:
            filters.append(f"agent_type = '{_esc(agent_type)}'")
        if role:
            filters.append(f"role = '{_esc(role)}'")
        if days:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            filters.append(f"timestamp > '{cutoff}'")

        if filters:
            search_query = search_query.where(" AND ".join(filters))

        df = search_query.limit(limit).to_pandas()

        results = []
        for _, row in df.iterrows():
            results.append(SearchResult(
                id=int(row["id"]),
                agent_type=row["agent_type"],
                project=row["project"],
                session_id=row["session_id"],
                role=row["role"],
                content=row["text"],
                timestamp=datetime.fromisoformat(row["timestamp"]),
                file_paths=[],
                issue_numbers=[],
                score=float(row.get("_distance", 0)),
            ))
        return results

    def delete_by_source(self, source_file: str):
        """Delete all vectors from a source file."""
        table = self._get_table()
        escaped = source_file.replace("'", "''")
        try:
            table.delete(f"source_file = '{escaped}'")
        except (OSError, ValueError):
            pass  # Table might be empty or have no matching rows
