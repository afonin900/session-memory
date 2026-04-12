# storage/sqlite_fts.py
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

from storage.models import SearchResult, SessionFragment

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_type TEXT NOT NULL,
    project TEXT NOT NULL,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    timestamp DATETIME NOT NULL,
    file_paths TEXT DEFAULT '[]',
    issue_numbers TEXT DEFAULT '[]',
    source_file TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS sessions_fts USING fts5(
    content, file_paths, project,
    content=sessions_log, content_rowid=id
);

CREATE TABLE IF NOT EXISTS indexed_files (
    source_file TEXT PRIMARY KEY,
    mtime REAL NOT NULL,
    entry_count INTEGER DEFAULT 0,
    indexed_at DATETIME DEFAULT (datetime('now'))
);
"""

_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS sessions_log_ai AFTER INSERT ON sessions_log BEGIN
    INSERT INTO sessions_fts(rowid, content, file_paths, project)
    VALUES (new.id, new.content, new.file_paths, new.project);
END;

CREATE TRIGGER IF NOT EXISTS sessions_log_ad AFTER DELETE ON sessions_log BEGIN
    INSERT INTO sessions_fts(sessions_fts, rowid, content, file_paths, project)
    VALUES ('delete', old.id, old.content, old.file_paths, old.project);
END;
"""


_KNOWLEDGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS knowledge_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL UNIQUE,
    project TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    doc_type TEXT NOT NULL DEFAULT 'doc',
    tags TEXT DEFAULT '[]',
    content TEXT NOT NULL,
    date TEXT NOT NULL,
    importance TEXT DEFAULT 'medium',
    mtime REAL NOT NULL,
    indexed_at DATETIME DEFAULT (datetime('now'))
);

CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
    title, content, tags, project,
    content=knowledge_files, content_rowid=id
);

CREATE TRIGGER IF NOT EXISTS knowledge_files_ai AFTER INSERT ON knowledge_files BEGIN
    INSERT INTO knowledge_fts(rowid, title, content, tags, project)
    VALUES (new.id, new.title, new.content, new.tags, new.project);
END;

CREATE TRIGGER IF NOT EXISTS knowledge_files_ad AFTER DELETE ON knowledge_files BEGIN
    INSERT INTO knowledge_fts(knowledge_fts, rowid, title, content, tags, project)
    VALUES ('delete', old.id, old.title, old.content, old.tags, old.project);
END;

CREATE TRIGGER IF NOT EXISTS knowledge_files_au AFTER UPDATE ON knowledge_files BEGIN
    INSERT INTO knowledge_fts(knowledge_fts, rowid, title, content, tags, project)
    VALUES ('delete', old.id, old.title, old.content, old.tags, old.project);
    INSERT INTO knowledge_fts(rowid, title, content, tags, project)
    VALUES (new.id, new.title, new.content, new.tags, new.project);
END;
"""


_FTS5_OPERATORS = {"AND", "OR", "NOT", "NEAR"}
# FTS5 special characters that cause syntax errors when unescaped.
# Dot (.) triggers "fts5: syntax error near '.'" for tokens like "Analytics.astro".
_FTS5_SPECIAL = set('-*%^().":+~')


def _escape_fts5_query(query: str) -> str:
    """Escape tokens containing FTS5 special characters.
    Tokens with special chars are wrapped in double quotes.
    Explicit FTS5 operators (AND, OR, NOT, NEAR) are left intact.
    Already-quoted tokens are left intact.
    """
    if not query:
        return ""
    tokens = query.split()
    escaped = []
    for token in tokens:
        if token in _FTS5_OPERATORS:
            escaped.append(token)
        elif token.startswith('"') and token.endswith('"'):
            escaped.append(token)
        elif any(c in _FTS5_SPECIAL for c in token):
            # Escape any embedded double-quotes before wrapping
            safe = token.replace('"', '""')
            escaped.append(f'"{safe}"')
        else:
            escaped.append(token)
    return " ".join(escaped)


def _row_to_result(row: sqlite3.Row, score: float = 0.0) -> SearchResult:
    return SearchResult(
        id=row["id"],
        agent_type=row["agent_type"],
        project=row["project"],
        session_id=row["session_id"],
        role=row["role"],
        content=row["content"],
        timestamp=datetime.fromisoformat(row["timestamp"]),
        file_paths=json.loads(row["file_paths"]),
        issue_numbers=json.loads(row["issue_numbers"]),
        score=score,
    )


class SqliteFtsStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def init_db(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(_SCHEMA)
        self._conn.executescript(_TRIGGERS)
        self._conn.executescript(_KNOWLEDGE_SCHEMA)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS graph_edges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_file TEXT NOT NULL,
                source_project TEXT NOT NULL,
                target_slug TEXT NOT NULL,
                target_file TEXT,
                UNIQUE(source_file, target_slug)
            )
        """)
        self._conn.commit()

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def insert_entries(self, entries: list) -> list[int]:
        """Insert LogEntry list, return list of inserted IDs."""
        ids = []
        for e in entries:
            cursor = self._conn.execute(
                """INSERT INTO sessions_log
                   (agent_type, project, session_id, role, content,
                    timestamp, file_paths, issue_numbers, source_file)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    e.agent_type, e.project, e.session_id, e.role, e.content,
                    e.timestamp.isoformat(), json.dumps(e.file_paths),
                    json.dumps(e.issue_numbers), e.source_file,
                ),
            )
            ids.append(cursor.lastrowid)
        self._conn.commit()
        return ids

    def search(
        self,
        query: str,
        project: str | None = None,
        agent_type: str | None = None,
        days: int | None = None,
        role: str | None = None,
        limit: int = 20,
    ) -> list[SearchResult]:
        """FTS5 keyword search."""
        query = _escape_fts5_query(query)
        conditions = ["sessions_fts MATCH ?"]
        params: list = [query]

        if project:
            conditions.append("s.project = ?")
            params.append(project)
        if agent_type:
            conditions.append("s.agent_type = ?")
            params.append(agent_type)
        if days:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            conditions.append("s.timestamp > ?")
            params.append(cutoff)
        if role:
            conditions.append("s.role = ?")
            params.append(role)

        params.append(limit)
        where = " AND ".join(conditions)

        rows = self._conn.execute(
            f"""SELECT s.*, sessions_fts.rank as score
                FROM sessions_fts
                JOIN sessions_log s ON s.id = sessions_fts.rowid
                WHERE {where}
                ORDER BY sessions_fts.rank
                LIMIT ?""",
            params,
        ).fetchall()

        return [_row_to_result(r, score=r["score"]) for r in rows]

    def get_by_id(self, entry_id: int) -> SearchResult | None:
        row = self._conn.execute(
            "SELECT * FROM sessions_log WHERE id = ?", (entry_id,)
        ).fetchone()
        return _row_to_result(row) if row else None

    def get_context(self, entry_id: int, window: int = 2) -> SessionFragment:
        """Get a context window around a search result."""
        center = self.get_by_id(entry_id)
        if not center:
            raise ValueError(f"Entry {entry_id} not found")

        before_rows = self._conn.execute(
            """SELECT * FROM sessions_log
               WHERE session_id = ? AND id < ?
               ORDER BY id DESC LIMIT ?""",
            (center.session_id, entry_id, window),
        ).fetchall()

        after_rows = self._conn.execute(
            """SELECT * FROM sessions_log
               WHERE session_id = ? AND id > ?
               ORDER BY id ASC LIMIT ?""",
            (center.session_id, entry_id, window),
        ).fetchall()

        return SessionFragment(
            match=center,
            before=[_row_to_result(r) for r in reversed(before_rows)],
            after=[_row_to_result(r) for r in after_rows],
            session_id=center.session_id,
            project=center.project,
        )

    def mark_indexed(self, source_file: str, mtime: float, entry_count: int):
        self._conn.execute(
            """INSERT OR REPLACE INTO indexed_files
               (source_file, mtime, entry_count) VALUES (?, ?, ?)""",
            (source_file, mtime, entry_count),
        )
        self._conn.commit()

    def is_indexed(self, source_file: str, mtime: float) -> bool:
        row = self._conn.execute(
            "SELECT mtime FROM indexed_files WHERE source_file = ?",
            (source_file,),
        ).fetchone()
        return row is not None and row["mtime"] == mtime

    def delete_by_source(self, source_file: str):
        """Delete all entries from a source file (for re-indexing)."""
        self._conn.execute(
            "DELETE FROM sessions_log WHERE source_file = ?", (source_file,)
        )
        self._conn.execute(
            "DELETE FROM indexed_files WHERE source_file = ?", (source_file,)
        )
        self._conn.commit()

    def count_entries(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM sessions_log").fetchone()[0]

    def get_entries_by_ids(self, ids: list[int]) -> list:
        """Return list of (id, LogEntry) tuples for the given SQLite row IDs.

        Used by incremental vector indexing to fetch only newly inserted entries.
        Content is truncated to 1000 chars — same as get_entries_batch.
        """
        if not ids:
            return []
        from storage.models import LogEntry
        placeholders = ",".join("?" * len(ids))
        rows = self._conn.execute(
            f"SELECT id, agent_type, project, session_id, role, SUBSTR(content, 1, 1000) as content, "
            f"timestamp, file_paths, issue_numbers, source_file "
            f"FROM sessions_log WHERE id IN ({placeholders}) ORDER BY id",
            ids,
        ).fetchall()
        result = []
        for row in rows:
            entry = LogEntry(
                agent_type=row["agent_type"],
                project=row["project"],
                session_id=row["session_id"],
                role=row["role"],
                content=row["content"],
                timestamp=datetime.fromisoformat(row["timestamp"]),
                file_paths=json.loads(row["file_paths"]),
                issue_numbers=json.loads(row["issue_numbers"]),
                source_file=row["source_file"],
            )
            result.append((row["id"], entry))
        return result

    def get_entries_batch(self, offset: int, limit: int) -> list:
        """Return list of (id, LogEntry) tuples for vector indexing.

        Content is truncated to 1000 chars at SQL level — sufficient for 256-token
        embedder limit and avoids loading full 593KB max entries into memory.
        """
        from storage.models import LogEntry
        rows = self._conn.execute(
            "SELECT id, agent_type, project, session_id, role, SUBSTR(content, 1, 1000) as content, "
            "timestamp, file_paths, issue_numbers, source_file "
            "FROM sessions_log ORDER BY id LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        result = []
        for row in rows:
            entry = LogEntry(
                agent_type=row["agent_type"],
                project=row["project"],
                session_id=row["session_id"],
                role=row["role"],
                content=row["content"],
                timestamp=datetime.fromisoformat(row["timestamp"]),
                file_paths=json.loads(row["file_paths"]),
                issue_numbers=json.loads(row["issue_numbers"]),
                source_file=row["source_file"],
            )
            result.append((row["id"], entry))
        return result

    def stats(self) -> dict:
        total = self._conn.execute("SELECT COUNT(*) FROM sessions_log").fetchone()[0]
        by_project = {}
        for row in self._conn.execute(
            "SELECT project, COUNT(*) as cnt FROM sessions_log GROUP BY project"
        ):
            by_project[row["project"]] = row["cnt"]
        by_agent = {}
        for row in self._conn.execute(
            "SELECT agent_type, COUNT(*) as cnt FROM sessions_log GROUP BY agent_type"
        ):
            by_agent[row["agent_type"]] = row["cnt"]
        return {"total": total, "by_project": by_project, "by_agent": by_agent}

    def search_knowledge(
        self,
        query: str,
        project: str | None = None,
        doc_type: str | None = None,
        days: int | None = None,
        limit: int = 20,
    ) -> list[SearchResult]:
        """FTS5 search over knowledge_files."""
        query = _escape_fts5_query(query)
        conditions = ["knowledge_fts MATCH ?"]
        params: list = [query]

        if project:
            conditions.append("k.project = ?")
            params.append(project)
        if doc_type:
            conditions.append("k.doc_type = ?")
            params.append(doc_type)
        if days:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
            conditions.append("k.date > ?")
            params.append(cutoff)

        params.append(limit)
        where = " AND ".join(conditions)

        rows = self._conn.execute(
            f"""SELECT k.id, k.project, k.title, k.doc_type, k.content,
                       k.date, k.file_path, knowledge_fts.rank as score
                FROM knowledge_fts
                JOIN knowledge_files k ON k.id = knowledge_fts.rowid
                WHERE {where}
                ORDER BY knowledge_fts.rank
                LIMIT ?""",
            params,
        ).fetchall()

        results = []
        for r in rows:
            results.append(SearchResult(
                id=10_000_000 + r["id"],
                agent_type="knowledge",
                project=r["project"],
                session_id=f"knowledge-{r['id']}",
                role="document",
                content=r["content"][:500],
                timestamp=datetime.fromisoformat(r["date"]) if r["date"] else datetime.now(timezone.utc),
                file_paths=[r["file_path"]],
                issue_numbers=[],
                score=r["score"],
            ))
        return results

    def knowledge_stats(self) -> dict:
        """Stats for knowledge_files table."""
        try:
            total = self._conn.execute("SELECT COUNT(*) FROM knowledge_files").fetchone()[0]
        except sqlite3.OperationalError:
            return {"total": 0, "by_type": {}, "by_project": {}}

        by_type = {}
        for row in self._conn.execute(
            "SELECT doc_type, COUNT(*) as cnt FROM knowledge_files GROUP BY doc_type"
        ):
            by_type[row["doc_type"]] = row["cnt"]

        by_project = {}
        for row in self._conn.execute(
            "SELECT project, COUNT(*) as cnt FROM knowledge_files GROUP BY project"
        ):
            by_project[row["project"]] = row["cnt"]

        return {"total": total, "by_type": by_type, "by_project": by_project}
