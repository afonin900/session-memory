#!/usr/bin/env python3
# mcp_server.py — Session Memory MCP Server
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from fastmcp import FastMCP

from config import SQLITE_PATH, DB_DIR
from storage.sqlite_fts import SqliteFtsStore
from core.search import SearchEngine

mcp = FastMCP("Session Memory")

# Lazy-init state
_store: SqliteFtsStore | None = None
_engine: SearchEngine | None = None


def _get_store() -> SqliteFtsStore:
    import os
    db_dir = os.environ.get("SM_DB_DIR")
    db_path = Path(db_dir) / "sessions.db" if db_dir else SQLITE_PATH
    store = SqliteFtsStore(db_path)
    store.init_db()
    return store


def _get_vector_store():
    """Create LanceDB store if dependencies available."""
    import os
    try:
        from storage.lancedb_store import LanceDBStore
        from core.embedder import Embedder
        db_dir_env = os.environ.get("SM_DB_DIR")
        vectors_dir = Path(db_dir_env) / "vectors" if db_dir_env else DB_DIR / "vectors"
        vstore = LanceDBStore(vectors_dir, Embedder())
        vstore.init_db()
        return vstore
    except ImportError:
        return None


def _get_engine() -> SearchEngine:
    global _store, _engine
    if _engine is None:
        _store = _get_store()
        vstore = _get_vector_store()
        _engine = SearchEngine(store=_store, vector_store=vstore)
    return _engine


@mcp.tool
def search_sessions(
    query: str,
    project: str | None = None,
    days: int = 30,
    limit: int = 5,
) -> list[dict]:
    """Search across AI agent session logs. Returns compact results with context snippets.

    Args:
        query: Search query (keyword or semantic)
        project: Filter by project alias (hq, kfs, jh, bb, aie...)
        days: Search depth in days (default 30)
        limit: Maximum number of results (default 5)
    """
    engine = _get_engine()

    # Use RRF (all) if vector store available, fallback to keyword
    mode = "all" if engine.vector_store is not None else "keyword"

    try:
        fragments = engine.search(
            query=query,
            mode=mode,
            project=project,
            days=days,
            role=None,
            limit=limit * 2,  # fetch extra to compensate for system role filtering
        )
    except (ValueError, Exception):
        # Fallback to keyword if RRF fails (e.g., stale vector IDs)
        if mode != "keyword":
            fragments = engine.search(
                query=query,
                mode="keyword",
                project=project,
                days=days,
                role=None,
                limit=limit * 2,
            )
        else:
            return []

    results = []
    for frag in fragments:
        match = frag.match

        # Filter noise: system role + short content (metadata, "Tool loaded.", ".")
        if match.role == "system" or len(match.content) < 50:
            continue

        ts = match.timestamp.strftime("%Y-%m-%d %H:%M")
        session_short = frag.session_id[:8]
        snippet = match.content[:200].replace("\n", " ")

        context_entries = []
        for entry in frag.before:
            if entry.role != "system":
                context_entries.append(f"[{entry.role}] {entry.content[:100].replace(chr(10), ' ')}")
        for entry in frag.after:
            if entry.role != "system":
                context_entries.append(f"[{entry.role}] {entry.content[:100].replace(chr(10), ' ')}")

        results.append({
            "ts": ts,
            "project": frag.project,
            "session": session_short,
            "snippet": snippet,
            "context": context_entries,
        })

        if len(results) >= limit:
            break

    return results if results else [{"info": f"No results for '{query}' in last {days} days"}]


if __name__ == "__main__":
    mcp.run()
