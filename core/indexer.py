import gc
import os
import time
from pathlib import Path
from parsers.registry import get_parsers
from storage.sqlite_fts import SqliteFtsStore


# Memory ceiling: 2GB RSS — trigger forced cleanup if exceeded
_RSS_CEILING_MB = 2048
_LANCE_RECONNECT_EVERY = 50_000  # flush Arrow memory pools
_GC_EVERY = 10_000  # garbage collect cycle


def _get_rss_mb() -> float:
    """Get current process RSS in MB (macOS/Linux)."""
    try:
        import resource
        # maxrss on macOS is in bytes
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return rss / (1024 * 1024) if os.uname().sysname == "Darwin" else rss / 1024
    except Exception:
        return 0


class Indexer:
    def __init__(
        self,
        store: SqliteFtsStore,
        claude_logs_base: Path | None = None,
        vector_store=None,
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
        """Full reindex — Phase 1: SQLite FTS, Phase 2: vectors in-process."""
        files_indexed = 0
        entries_added = 0

        # Phase 1: SQLite FTS only (light, no embeddings)
        for parser, path in self._discover_all():
            if not path.exists():
                continue
            mtime = path.stat().st_mtime

            self.store.delete_by_source(str(path))
            if self.vector_store:
                self.vector_store.delete_by_source(str(path))

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

    def _index_vectors_inprocess(self, chunk_size: int = 1000):
        """Embed all entries in-process with memory management.

        Single model load, processes in chunks of 1000 entries.
        gc.collect every 10k, LanceDB reconnect every 50k, hard ceiling at 2GB RSS.
        """
        import torch

        total = self.store.count_entries()
        print(f"Phase 2 (vectors): {total} entries to embed")
        t0 = time.time()
        embedded_total = 0

        for offset in range(0, total, chunk_size):
            batch_t0 = time.time()
            rows = self.store.get_entries_batch(offset, chunk_size)
            if not rows:
                continue

            entries = [r[1] for r in rows]
            ids = [r[0] for r in rows]

            # Embed and write to LanceDB (insert_entries handles internal chunking)
            with torch.no_grad():
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
            if rss > _RSS_CEILING_MB:
                print(f"  [warning] RSS {rss:.0f}MB > ceiling {_RSS_CEILING_MB}MB — forcing cleanup")
                self.vector_store.reconnect()
                gc.collect()
                torch.mps.empty_cache() if hasattr(torch, "mps") else None

        total_time = time.time() - t0
        print(f"Phase 2 complete: {embedded_total} entries in {total_time/60:.1f} min")

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
