import pytest
from pathlib import Path
from core.knowledge import parse_knowledge_file, discover_knowledge_files, index_knowledge


def test_parse_frontmatter():
    content = """---
title: Test Document
type: decision
project: kfs
date: 2026-04-12
tags: [marketing, content]
importance: high
---

# Content

Decision body text here.
"""
    result = parse_knowledge_file(content, "/path/to/file.md")
    assert result["title"] == "Test Document"
    assert result["doc_type"] == "decision"
    assert result["project"] == "kfs"
    assert result["tags"] == ["marketing", "content"]
    assert result["importance"] == "high"
    assert "Decision body text" in result["content"]


def test_parse_no_frontmatter():
    content = "# Just a heading\n\nSome text."
    result = parse_knowledge_file(content, "/home/user/Knowledge/kfs/2026/04/doc.md")
    assert result["title"] == "Just a heading"
    assert result["project"] == "kfs"
    assert result["doc_type"] == "doc"


def test_parse_extracts_project_from_path():
    content = "---\ntitle: Test\n---\nBody"
    result = parse_knowledge_file(content, "/home/user/Knowledge/job-hunter/2026/04/test.md")
    assert result["project"] == "job-hunter"


def test_discover_knowledge_files(tmp_path):
    (tmp_path / "kfs" / "2026" / "04").mkdir(parents=True)
    (tmp_path / "kfs" / "2026" / "04" / "doc1.md").write_text("# Doc 1")
    (tmp_path / "global" / "2026").mkdir(parents=True)
    (tmp_path / "global" / "2026" / "doc2.md").write_text("# Doc 2")
    (tmp_path / "readme.txt").write_text("not md")

    files = discover_knowledge_files(tmp_path)
    assert len(files) == 2
    assert all(f.suffix == ".md" for f in files)


def test_index_knowledge(tmp_path):
    (tmp_path / "kb" / "kfs" / "2026" / "04").mkdir(parents=True)
    (tmp_path / "kb" / "kfs" / "2026" / "04" / "decision.md").write_text(
        "---\ntitle: Test Decision\ntype: decision\nproject: kfs\ndate: 2026-04-12\ntags: [test]\n---\n\nDecision body."
    )

    db_path = tmp_path / "test.db"
    from storage.sqlite_fts import SqliteFtsStore
    store = SqliteFtsStore(db_path)
    store.init_db()

    stats = index_knowledge(store, base_dir=tmp_path / "kb")
    assert stats["files_indexed"] == 1
    assert stats["entries_added"] == 1

    # Re-index should skip
    stats2 = index_knowledge(store, base_dir=tmp_path / "kb")
    assert stats2["files_skipped"] == 1
    assert stats2["entries_added"] == 0

    store.close()
