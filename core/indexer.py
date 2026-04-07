import fcntl
import gc
import os
import subprocess
import time
from pathlib import Path
from core.noise_filter import should_index_vector
from parsers.registry import get_parsers
from storage.sqlite_fts import SqliteFtsStore


# Memory ceiling: 1GB RSS — trigger forced cleanup if exceeded
_RSS_CEILING_MB = 1024
_LANCE_RECONNECT_EVERY = 5_000   # flush Arrow memory pools (was 50_000)
_GC_EVERY = 2_500                # garbage collect cycle (was 10_000)


def _get_rss_mb() -> float:
    """Get current process RSS in MB (macOS/Linux).

    Uses 'ps' to get live RSS instead of resource.getrusage which returns
    PEAK RSS on macOS — useless for detecting memory growth during indexing.
    """
    try:
        out = subprocess.check_output(
            ["ps", "-o", "rss=", "-p", str(os.getpid())],
            text=True,
        )
        return int(out.strip()) / 1024  # ps reports KB
    except Exception:
        return 0


class Indexer:
    def __init__(
        self,
        store: SqliteFtsStore,
        claude_logs_base: Path | None = None,
        vector_store=None,
        rss_ceiling_mb: int | None = None,
    ):
        self.store = store
        self.vector_store = vector_store
        self.parsers = get_parsers(claude_logs_base=claude_logs_base)
        self._rss_ceiling_mb = rss_ceiling_mb if rss_ceiling_mb is not None else _RSS_CEILING_MB

    def _discover_all(self):
        """Discover all session files from all parsers."""
        for parser in self.parsers:
            for path in parser.discover_sessions():
                yield parser, path

    def _should_skip_file(self, path: Path, skip_recent_minutes: int = 60) -> bool:
        """Skip files modified within the last N minutes (likely active sessions)."""
        try:
            age_seconds = time.time() - path.stat().st_mtime
            return age_seconds < skip_recent_minutes * 60
        except OSError:
            return True  # skip if we can't stat the file

    def index_full(self) -> dict:
        """Full reindex — Phase 1: SQLite FTS, Phase 2: vectors in-process."""
        files_indexed = 0
        entries_added = 0

        # Drop and recreate vector table to eliminate fragmentation (15K+ version files, 7K deletions)
        if self.vector_store:
            print("Dropping vector table for clean full reindex...")
            self.vector_store.drop_table()
            print("Vector table dropped and recreated.")

        # Phase 1: SQLite FTS only (light, no embeddings)
        for parser, path in self._discover_all():
            if not path.exists():
                continue
            mtime = path.stat().st_mtime

            self.store.delete_by_source(str(path))
            # No need to delete from vector_store — table was already dropped above

            entries = parser.parse_session(path)
            if entries:
                self.store.insert_entries(entries)
                entries_added += len(entries)
            self.store.mark_indexed(str(path), mtime, len(entries))
            files_indexed += 1
            del entries

        print(f"Phase 1 (FTS) complete: {files_indexed} files, {entries_added} entries")

        # Phase 2: Vector embeddings in-process (single model load)
        if self.vector_store:
            self._index_vectors_inprocess()

        return {"files_indexed": files_indexed, "entries_added": entries_added}

    def _index_vectors_inprocess(self, chunk_size: int = 100, entry_ids: list[int] | None = None):
        """Embed entries in-process with memory management.

        Single model load, processes in chunks of 100 entries.
        gc.collect every 2.5k, LanceDB reconnect every 5k, hard ceiling at 1GB RSS.

        Args:
            chunk_size: Number of entries per embedding batch.
            entry_ids: If provided, only embed these SQLite row IDs (incremental mode).
                       If None, embed all entries in the store (full reindex mode).
        """
        existing_ids: set[int] = set()

        if entry_ids is not None:
            # Incremental mode: fetch only the specified IDs
            total = len(entry_ids)
            print(f"Phase 2 (vectors): {total} new entries to embed")

            def _iter_batches():
                for start in range(0, total, chunk_size):
                    batch_ids = entry_ids[start:start + chunk_size]
                    yield self.store.get_entries_by_ids(batch_ids)
        else:
            # Full reindex mode: iterate all entries via OFFSET/LIMIT
            total = self.store.count_entries()
            existing_ids = self.vector_store.get_existing_ids()
            if existing_ids:
                print(f"Skipping {len(existing_ids)} already embedded entries, {total - len(existing_ids)} remaining")
            print(f"Phase 2 (vectors): {total} entries to embed")

            def _iter_batches():
                for offset in range(0, total, chunk_size):
                    yield self.store.get_entries_batch(offset, chunk_size)

        t0 = time.time()
        embedded_total = 0

        for rows in _iter_batches():
            batch_t0 = time.time()
            # In full reindex mode, skip entries already in LanceDB
            if entry_ids is None and existing_ids:
                rows = [(id_, entry) for id_, entry in rows if id_ not in existing_ids]
            # Filter noise before embedding
            rows = [(id_, entry) for id_, entry in rows if should_index_vector(entry)]
            if not rows:
                continue

            entries = [r[1] for r in rows]
            ids = [r[0] for r in rows]

            # Embed and write to LanceDB (insert_entries handles internal chunking)
            self.vector_store.insert_entries(entries, ids)

            embedded_total += len(entries)
            elapsed = time.time() - t0
            batch_elapsed = time.time() - batch_t0
            rate = embedded_total / elapsed if elapsed > 0 else 0
            eta_min = (total - embedded_total) / rate / 60 if rate > 0 else 0
            rss = _get_rss_mb()

            print(
                f"  {embedded_total}/{total} ({100*embedded_total/total:.1f}%) "
                f"| batch {batch_elapsed:.1f}s | {rate:.0f} entries/s "
                f"| ETA {eta_min:.0f}min | RSS {rss:.0f}MB"
            )

            # Cleanup
            del entries, ids, rows

            # Periodic gc
            if embedded_total % _GC_EVERY == 0:
                gc.collect()

            # Periodic LanceDB reconnect to flush Arrow memory pools
            if embedded_total % _LANCE_RECONNECT_EVERY == 0:
                print(f"  [maintenance] LanceDB reconnect at {embedded_total}")
                self.vector_store.reconnect()
                gc.collect()

            # Hard memory ceiling
            if rss > self._rss_ceiling_mb:
                print(f"  [cleanup] RSS {rss:.0f}MB > {self._rss_ceiling_mb}MB limit — freeing memory")
                self.vector_store.reconnect()
                gc.collect()

        total_time = time.time() - t0
        print(f"Phase 2 complete: {embedded_total} entries in {total_time/60:.1f} min")

    def index_incremental(self) -> dict:
        """Incremental index — only new or changed files.

        Two-phase approach (mirrors index_full):
        - Phase 1: SQLite FTS only — parse + insert entries, no embeddings.
        - Phase 2: Vector embeddings in batches of 250 via _index_vectors_inprocess,
                   passing only the IDs of newly inserted entries so existing vectors
                   are not duplicated in LanceDB.
        """
        files_indexed = 0
        files_skipped = 0
        entries_added = 0
        new_entry_ids: list[int] = []

        # Phase 1: FTS only (light, no embeddings)
        for parser, path in self._discover_all():
            if not path.exists():
                continue
            mtime = path.stat().st_mtime

            if self.store.is_indexed(str(path), mtime):
                files_skipped += 1
                continue

            # Re-index changed/new file
            self.store.delete_by_source(str(path))
            if self.vector_store:
                self.vector_store.delete_by_source(str(path))

            entries = parser.parse_session(path)
            if entries:
                ids = self.store.insert_entries(entries)
                new_entry_ids.extend(ids)
                entries_added += len(entries)
            self.store.mark_indexed(str(path), mtime, len(entries))
            files_indexed += 1
            del entries

        print(f"Phase 1 (FTS) complete: {files_indexed} files, {entries_added} entries")

        # Phase 2: Vector embeddings for new entries only (single model load)
        if self.vector_store and new_entry_ids:
            self._index_vectors_inprocess(entry_ids=new_entry_ids)

        return {"files_indexed": files_indexed, "files_skipped": files_skipped, "entries_added": entries_added}

    def index_fts_only(self, skip_recent_minutes: int = 60) -> dict:
        """Phase 1 only: FTS indexing, skip recent files, no vector store needed."""
        files_indexed = 0
        files_skipped_recent = 0
        files_skipped_unchanged = 0
        entries_added = 0

        for parser, path in self._discover_all():
            if not path.exists():
                continue

            if self._should_skip_file(path, skip_recent_minutes):
                files_skipped_recent += 1
                continue

            mtime = path.stat().st_mtime

            if self.store.is_indexed(str(path), mtime):
                files_skipped_unchanged += 1
                continue

            self.store.delete_by_source(str(path))
            entries = parser.parse_session(path) or []
            if entries:
                self.store.insert_entries(entries)
                entries_added += len(entries)
            self.store.mark_indexed(str(path), mtime, len(entries))
            files_indexed += 1
            del entries

        return {
            "files_indexed": files_indexed,
            "files_skipped_recent": files_skipped_recent,
            "files_skipped_unchanged": files_skipped_unchanged,
            "entries_added": entries_added,
        }

    def index_vectors_bg(
        self,
        lock_path: str = "/tmp/session-memory-vectors.lock",
        skip_recent_minutes: int = 60,
    ) -> dict:
        """Phase 2 only: vector embeddings with lock file protection.

        Acquires exclusive lock. If another process holds it, exits silently.
        Skips files modified within skip_recent_minutes.
        """
        if not self.vector_store:
            return {"status": "no_vector_store"}

        lock_file = open(lock_path, "w")
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (IOError, OSError):
            lock_file.close()
            return {"status": "locked"}

        try:
            # FTS for any files not yet indexed (skip recent)
            new_entry_ids: list[int] = []
            for parser, path in self._discover_all():
                if not path.exists():
                    continue
                if self._should_skip_file(path, skip_recent_minutes):
                    continue
                mtime = path.stat().st_mtime
                if self.store.is_indexed(str(path), mtime):
                    continue

                self.store.delete_by_source(str(path))
                self.vector_store.delete_by_source(str(path))
                entries = parser.parse_session(path) or []
                if entries:
                    ids = self.store.insert_entries(entries)
                    new_entry_ids.extend(ids)
                self.store.mark_indexed(str(path), mtime, len(entries))
                del entries

            # Embed entries not yet in LanceDB
            if new_entry_ids:
                self._index_vectors_inprocess(entry_ids=new_entry_ids)
            else:
                # Gap from prior FTS-only runs — embed all unembedded entries
                self._index_vectors_inprocess()

            return {"status": "completed"}
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)
            lock_file.close()
