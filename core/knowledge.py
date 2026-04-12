# core/knowledge.py — Knowledge Base parser and indexer
import re
import json
from pathlib import Path
from datetime import datetime

from config import KNOWLEDGE_BASE


def parse_knowledge_file(content: str, file_path: str) -> dict:
    """Parse a Knowledge MD file with optional YAML frontmatter."""
    result = {
        "title": "",
        "doc_type": "doc",
        "project": "global",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "tags": [],
        "importance": "medium",
        "content": content,
        "file_path": file_path,
    }

    # Extract project from path: ~/Knowledge/{project}/...
    path_parts = Path(file_path).parts
    for i, part in enumerate(path_parts):
        if part == "Knowledge" and i + 1 < len(path_parts):
            result["project"] = path_parts[i + 1]
            break

    # Parse YAML frontmatter
    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", content, re.DOTALL)
    if fm_match:
        frontmatter_text = fm_match.group(1)
        body = fm_match.group(2)
        result["content"] = body

        for line in frontmatter_text.split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key_match = re.match(r"^(\w+):\s*(.+)$", line)
            if not key_match:
                continue
            key, value = key_match.group(1), key_match.group(2).strip()
            if key == "title":
                result["title"] = value
            elif key == "type":
                result["doc_type"] = value
            elif key == "project":
                result["project"] = value
            elif key == "date":
                result["date"] = value
            elif key == "importance":
                result["importance"] = value
            elif key == "tags":
                result["tags"] = re.findall(r"[\w-]+", value)

    if not result["title"]:
        heading_match = re.match(r"^#\s+(.+)$", result["content"], re.MULTILINE)
        if heading_match:
            result["title"] = heading_match.group(1).strip()

    return result


def discover_knowledge_files(base_dir: Path | None = None) -> list[Path]:
    """Find all .md files in ~/Knowledge/ recursively."""
    base = base_dir or KNOWLEDGE_BASE
    if not base.exists():
        return []
    return sorted(base.rglob("*.md"))


def index_knowledge(store, vector_store=None, base_dir: Path | None = None) -> dict:
    """Index all Knowledge MD files into SQLite + optionally LanceDB."""
    files = discover_knowledge_files(base_dir)
    stats = {"files_indexed": 0, "files_skipped": 0, "entries_added": 0}

    for file_path in files:
        file_str = str(file_path)
        mtime = file_path.stat().st_mtime

        row = store._conn.execute(
            "SELECT mtime FROM knowledge_files WHERE file_path = ?",
            (file_str,),
        ).fetchone()

        if row and row["mtime"] == mtime:
            stats["files_skipped"] += 1
            continue

        content = file_path.read_text(errors="replace")
        parsed = parse_knowledge_file(content, file_str)

        if row:
            store._conn.execute(
                """UPDATE knowledge_files SET
                   project=?, title=?, doc_type=?, tags=?, content=?,
                   date=?, importance=?, mtime=?, indexed_at=datetime('now')
                   WHERE file_path=?""",
                (parsed["project"], parsed["title"], parsed["doc_type"],
                 json.dumps(parsed["tags"]), parsed["content"],
                 parsed["date"], parsed["importance"], mtime, file_str),
            )
        else:
            store._conn.execute(
                """INSERT INTO knowledge_files
                   (file_path, project, title, doc_type, tags, content, date, importance, mtime)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (file_str, parsed["project"], parsed["title"], parsed["doc_type"],
                 json.dumps(parsed["tags"]), parsed["content"],
                 parsed["date"], parsed["importance"], mtime),
            )
            stats["entries_added"] += 1

        stats["files_indexed"] += 1

    store._conn.commit()

    if vector_store:
        _index_knowledge_vectors(store, vector_store)

    return stats


def _index_knowledge_vectors(store, vector_store):
    """Embed knowledge files into LanceDB."""
    from storage.models import LogEntry

    rows = store._conn.execute(
        "SELECT id, file_path, project, title, doc_type, content, date FROM knowledge_files"
    ).fetchall()

    entries = []
    ids = []
    for row in rows:
        entry = LogEntry(
            agent_type="knowledge",
            project=row["project"],
            session_id=f"knowledge-{row['id']}",
            role="document",
            content=f"{row['title']}\n\n{row['content'][:1000]}",
            timestamp=datetime.fromisoformat(row["date"]) if row["date"] else datetime.now(),
            source_file=row["file_path"],
        )
        entries.append(entry)
        ids.append(10_000_000 + row["id"])

    if entries:
        vector_store.insert_entries(entries, ids)
