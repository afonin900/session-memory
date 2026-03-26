from pathlib import Path
from parsers.base import BaseParser
from parsers.registry import get_parsers
from storage.sqlite_fts import SqliteFtsStore


class Indexer:
    def __init__(
        self,
        store: SqliteFtsStore,
        claude_logs_base: Path | None = None,
        vector_store=None,  # LanceDB store, added in Phase 2
    ):
        self.store = store
        self.vector_store = vector_store
        self.parsers = get_parsers(claude_logs_base=claude_logs_base)

    def _discover_all(self):
        """Discover all session files from all parsers."""
        for parser in self.parsers:
            for path in parser.discover_sessions():
                yield parser, path

    def index_full(self) -> dict:
        """Full reindex — process all discovered files."""
        files_indexed = 0
        entries_added = 0

        for parser, path in self._discover_all():
            mtime = path.stat().st_mtime

            # Delete old entries if re-indexing
            self.store.delete_by_source(str(path))
            if self.vector_store:
                self.vector_store.delete_by_source(str(path))

            entries = parser.parse_session(path)
            if entries:
                ids = self.store.insert_entries(entries)
                if self.vector_store:
                    self.vector_store.insert_entries(entries, ids)
                entries_added += len(entries)
            # Always mark as indexed (even empty files) to avoid re-parsing
            self.store.mark_indexed(str(path), mtime, len(entries))
            files_indexed += 1

        return {"files_indexed": files_indexed, "entries_added": entries_added}

    def index_incremental(self) -> dict:
        """Incremental index — only new or changed files."""
        files_indexed = 0
        files_skipped = 0
        entries_added = 0

        for parser, path in self._discover_all():
            mtime = path.stat().st_mtime

            if self.store.is_indexed(str(path), mtime):
                files_skipped += 1
                continue

            # Re-index changed file
            self.store.delete_by_source(str(path))
            if self.vector_store:
                self.vector_store.delete_by_source(str(path))

            entries = parser.parse_session(path)
            if entries:
                ids = self.store.insert_entries(entries)
                if self.vector_store:
                    self.vector_store.insert_entries(entries, ids)
                entries_added += len(entries)
            self.store.mark_indexed(str(path), mtime, len(entries))
            files_indexed += 1

        return {"files_indexed": files_indexed, "files_skipped": files_skipped, "entries_added": entries_added}
