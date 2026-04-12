# core/graph.py — Wiki-links parser and knowledge graph
import re
from pathlib import Path


def extract_wiki_links(content: str) -> list[str]:
    """Extract [[wiki-link]] references from markdown content."""
    matches = re.findall(r"\[\[([^\]]+)\]\]", content)
    seen = set()
    result = []
    for m in matches:
        m = m.strip()
        if m not in seen:
            seen.add(m)
            result.append(m)
    return result


def build_graph_edges(store, knowledge_base: Path) -> dict:
    """Parse all knowledge files, extract wiki-links, build graph_edges table."""
    store._conn.execute("""
        CREATE TABLE IF NOT EXISTS graph_edges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_file TEXT NOT NULL,
            source_project TEXT NOT NULL,
            target_slug TEXT NOT NULL,
            target_file TEXT,
            UNIQUE(source_file, target_slug)
        )
    """)
    store._conn.execute("DELETE FROM graph_edges")
    store._conn.commit()

    files = sorted(knowledge_base.rglob("*.md"))
    slug_map = {}
    for f in files:
        slug_map[f.stem] = str(f)

    edges_created = 0
    for f in files:
        content = f.read_text(errors="replace")
        links = extract_wiki_links(content)

        project = "global"
        parts = f.parts
        for i, part in enumerate(parts):
            if part == "Knowledge" and i + 1 < len(parts):
                project = parts[i + 1]
                break

        for link in links:
            target_file = slug_map.get(link)
            store._conn.execute(
                """INSERT OR IGNORE INTO graph_edges
                   (source_file, source_project, target_slug, target_file)
                   VALUES (?, ?, ?, ?)""",
                (str(f), project, link, target_file),
            )
            edges_created += 1

    store._conn.commit()
    return {"edges_created": edges_created, "files_processed": len(files)}


def get_related(store, file_path: str, limit: int = 10) -> list[dict]:
    """Get documents related to a given file via wiki-links."""
    rows = store._conn.execute(
        """SELECT target_slug, target_file FROM graph_edges
           WHERE source_file = ?
           UNION
           SELECT source_file as target_slug, source_file as target_file FROM graph_edges
           WHERE target_file = ?
           LIMIT ?""",
        (file_path, file_path, limit),
    ).fetchall()

    return [{"slug": r[0], "file": r[1]} for r in rows]
