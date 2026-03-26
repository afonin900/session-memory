#!/usr/bin/env python3
# cli.py — Session Memory CLI
import argparse
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from config import SQLITE_PATH, DB_DIR
from storage.sqlite_fts import SqliteFtsStore
from core.indexer import Indexer
from core.search import SearchEngine


def _get_store() -> SqliteFtsStore:
    db_dir = os.environ.get("SM_DB_DIR")
    db_path = Path(db_dir) / "sessions.db" if db_dir else SQLITE_PATH
    store = SqliteFtsStore(db_path)
    store.init_db()
    return store


def _get_vector_store():
    """Create LanceDB store if dependencies available."""
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


def _get_indexer(store: SqliteFtsStore) -> Indexer:
    claude_logs = os.environ.get("SM_CLAUDE_LOGS")
    claude_base = Path(claude_logs) if claude_logs else None
    return Indexer(store=store, claude_logs_base=claude_base)


def _format_fragment(frag, show_context=True):
    """Format a SessionFragment for terminal output."""
    lines = []
    header = (
        f"── [{frag.project}] {frag.match.timestamp:%Y-%m-%d %H:%M} "
        f"({frag.match.agent_type}, session {frag.session_id[:8]}) ──"
    )
    lines.append(header)

    if show_context:
        for entry in frag.before:
            content_preview = entry.content[:120].replace("\n", " ")
            lines.append(f"  [{entry.role}] {content_preview}")

    content_preview = frag.match.content[:200].replace("\n", " ")
    lines.append(f"> [{frag.match.role}] {content_preview}")

    if show_context:
        for entry in frag.after:
            content_preview = entry.content[:120].replace("\n", " ")
            lines.append(f"  [{entry.role}] {content_preview}")

    lines.append("─" * len(header))
    return "\n".join(lines)


def cmd_index(args):
    store = _get_store()
    vstore = _get_vector_store()
    indexer = _get_indexer(store)
    indexer.vector_store = vstore
    if args.quick:
        stats = indexer.index_incremental()
        mode = "Incremental"
    else:
        stats = indexer.index_full()
        mode = "Full"
    print(f"{mode} indexing complete:")
    print(f"  Indexed: {stats['files_indexed']} files, {stats['entries_added']} entries")
    if "files_skipped" in stats:
        print(f"  Skipped: {stats['files_skipped']} unchanged files")
    store.close()


def cmd_search(args):
    store = _get_store()
    vstore = _get_vector_store()
    engine = SearchEngine(store=store, vector_store=vstore)

    mode = "keyword"
    if args.semantic:
        mode = "semantic"
    elif getattr(args, "all", False):
        mode = "all"

    fragments = engine.search(
        query=args.query,
        mode=mode,
        project=args.project,
        agent_type=args.agent,
        days=args.days,
        role=args.role,
        limit=args.limit or 10,
    )

    if not fragments:
        print("No results found.")
        store.close()
        return

    for frag in fragments:
        print(_format_fragment(frag))
        print()

    store.close()


def cmd_stats(args):
    store = _get_store()
    stats = store.stats()
    print(f"Total entries: {stats['total']}")
    if stats["by_project"]:
        print("\nBy project:")
        for proj, cnt in sorted(stats["by_project"].items(), key=lambda x: -x[1]):
            print(f"  {proj}: {cnt}")
    if stats["by_agent"]:
        print("\nBy agent:")
        for agent, cnt in sorted(stats["by_agent"].items(), key=lambda x: -x[1]):
            print(f"  {agent}: {cnt}")
    store.close()


def main():
    parser = argparse.ArgumentParser(
        prog="sm",
        description="Session Memory — search across AI agent session logs",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # index
    p_index = sub.add_parser("index", help="Index session logs")
    p_index.add_argument("--quick", action="store_true", help="Incremental (new files only)")
    p_index.set_defaults(func=cmd_index)

    # search
    p_search = sub.add_parser("search", help="Search session logs")
    p_search.add_argument("query", help="Search query")
    p_search.add_argument("-s", "--semantic", action="store_true", help="Semantic search")
    p_search.add_argument("-a", "--all", action="store_true", help="Keyword + semantic merged")
    p_search.add_argument("-p", "--project", help="Filter by project (hq, kfs, jh...)")
    p_search.add_argument("--agent", help="Filter by agent type (claude, codex...)")
    p_search.add_argument("--days", type=int, help="Only last N days")
    p_search.add_argument("--role", help="Filter by role (user, assistant...)")
    p_search.add_argument("--limit", type=int, default=10, help="Max results (default 10)")
    p_search.set_defaults(func=cmd_search)

    # stats
    p_stats = sub.add_parser("stats", help="Show index statistics")
    p_stats.set_defaults(func=cmd_stats)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
