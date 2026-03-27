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
