#!/usr/bin/env python3
# cli.py — Session Memory CLI
import argparse
import os
import signal
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


def _get_indexer(store: SqliteFtsStore, rss_ceiling_mb: int | None = None) -> Indexer:
    claude_logs = os.environ.get("SM_CLAUDE_LOGS")
    claude_base = Path(claude_logs) if claude_logs else None
    return Indexer(store=store, claude_logs_base=claude_base, rss_ceiling_mb=rss_ceiling_mb)


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

    if args.fts_only:
        # Phase 1 only: no vector store, no heavy imports
        indexer = _get_indexer(store)
        stats = indexer.index_fts_only(skip_recent_minutes=args.skip_recent)
        print(f"FTS-only indexing complete:")
        print(f"  Indexed: {stats['files_indexed']} files, {stats['entries_added']} entries")
        print(f"  Skipped: {stats['files_skipped_unchanged']} unchanged, {stats['files_skipped_recent']} active")
    elif args.vectors_bg:
        # Phase 2 only: vectors with lock
        vstore = _get_vector_store()
        if not vstore:
            print("Error: vector store not available (missing dependencies?)")
            store.close()
            return
        indexer = _get_indexer(store, rss_ceiling_mb=args.max_memory)
        indexer.vector_store = vstore
        result = indexer.index_vectors_bg(skip_recent_minutes=args.skip_recent)
        if result["status"] == "locked":
            print("Another vectors process is running, skipping.")
        elif result["status"] == "completed":
            print("Background vector indexing complete.")
        else:
            print(f"Vector indexing status: {result['status']}")
    elif args.vectors_only or args.resume:
        vstore = _get_vector_store()
        if not vstore:
            print("Error: vector store not available (missing dependencies?)")
            store.close()
            return
        indexer = _get_indexer(store, rss_ceiling_mb=args.max_memory)
        indexer.vector_store = vstore
        indexer._index_vectors_inprocess()
        print("Vectors-only indexing complete.")
    elif args.quick:
        vstore = _get_vector_store()
        indexer = _get_indexer(store, rss_ceiling_mb=args.max_memory)
        indexer.vector_store = vstore
        stats = indexer.index_incremental()
        print(f"Incremental indexing complete:")
        print(f"  Indexed: {stats['files_indexed']} files, {stats['entries_added']} entries")
        if "files_skipped" in stats:
            print(f"  Skipped: {stats['files_skipped']} unchanged files")
    else:
        vstore = _get_vector_store()
        indexer = _get_indexer(store, rss_ceiling_mb=args.max_memory)
        indexer.vector_store = vstore
        stats = indexer.index_full()
        print(f"Full indexing complete:")
        print(f"  Indexed: {stats['files_indexed']} files, {stats['entries_added']} entries")

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


def cmd_init(args):
    from core.lifecycle import init_project
    results = init_project(
        project_name=args.project_name or Path.cwd().name,
        profile=args.profile,
    )
    print(f"Session Memory initialized ({args.profile} profile):")
    for f in results["created"]:
        print(f"  + {f}")
    for f in results["skipped"]:
        print(f"  ~ {f} (exists, skipped)")
    print(f"  Knowledge: {results['knowledge_dir']}")


def cmd_wake(args):
    import json as json_mod
    from core.lifecycle import wake
    result = wake(project=args.project)

    if args.hook:
        hook_output = {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": result["context"],
            }
        }
        print(json_mod.dumps(hook_output))
    else:
        print(result["context"])
        print(f"\n[status: {result['status']}]")


def cmd_sleep(args):
    from core.lifecycle import sleep
    result = sleep(
        project=args.project,
        transcript_path=args.transcript,
        summary=args.summary,
        session_id=args.session_id,
    )
    if result["status"] == "completed":
        ext = result.get("extracted", {})
        print(f"Session saved to {result['session_file']}")
        print(f"  Extracted: {ext.get('done',0)} done, {ext.get('not_done',0)} not done, {ext.get('decisions',0)} decisions")
    elif result["status"] == "already_processed":
        print(result["message"])
    else:
        print(f"Sleep status: {result['status']}")


def main():
    def _handle_signal(signum, frame):
        print(f"\nReceived signal {signum}, shutting down...")
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    parser = argparse.ArgumentParser(
        prog="sm",
        description="Session Memory — search across AI agent session logs",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # index
    p_index = sub.add_parser("index", help="Index session logs")
    p_index.add_argument("--quick", action="store_true", help="Incremental (new files only)")
    p_index.add_argument("--vectors-only", action="store_true", help="Skip FTS, only build vector embeddings from existing entries")
    p_index.add_argument("--resume", action="store_true",
                         help="Resume incomplete vector indexing — skips already-embedded entries (alias for --vectors-only)")
    p_index.add_argument("--max-memory", type=int, default=1500, metavar="MB",
                         help="RSS ceiling in MB before forced cleanup (default: 1500)")
    p_index.add_argument("--fts-only", action="store_true",
                         help="Phase 1 only: FTS indexing, no vectors, no heavy imports")
    p_index.add_argument("--vectors-bg", action="store_true",
                         help="Phase 2 only: vector embeddings with lock file (for background use)")
    p_index.add_argument("--skip-recent", type=int, default=60, metavar="MINUTES",
                         help="Skip files modified within last N minutes (default: 60)")
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

    # init
    p_init = sub.add_parser("init", help="Initialize session-memory in current project")
    p_init.add_argument("--profile", choices=["software", "content"], default="software",
                         help="Project profile (default: software)")
    p_init.add_argument("--project-name", help="Project name (default: directory name)")
    p_init.set_defaults(func=cmd_init)

    # wake
    p_wake = sub.add_parser("wake", help="Load session context (run at session start)")
    p_wake.add_argument("-p", "--project", help="Project name")
    p_wake.add_argument("--hook", action="store_true", help="Output JSON for Claude Code hook")
    p_wake.set_defaults(func=cmd_wake)

    # sleep
    p_sleep = sub.add_parser("sleep", help="Save session state (run at session end)")
    p_sleep.add_argument("-p", "--project", help="Project name")
    p_sleep.add_argument("--transcript", help="Path to transcript JSONL")
    p_sleep.add_argument("--summary", help="Explicit session summary")
    p_sleep.add_argument("--session-id", help="Session ID for idempotency")
    p_sleep.set_defaults(func=cmd_sleep)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
