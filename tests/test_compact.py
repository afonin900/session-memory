import json
from pathlib import Path
from unittest.mock import patch, MagicMock
from core.compact import collect_files_for_period, generate_digest, compact


def test_collect_files_for_period(tmp_path):
    (tmp_path / "2026" / "04").mkdir(parents=True)
    (tmp_path / "2026" / "04" / "01-plan.md").write_text("# Plan")
    (tmp_path / "2026" / "04" / "05-decision.md").write_text("# Decision")
    (tmp_path / "2026" / "04" / "DIGEST-2026-04.md").write_text("# Old digest")

    files = collect_files_for_period(tmp_path, "2026", "04")
    assert len(files) == 2  # DIGEST excluded
    assert all("DIGEST" not in f.name for f in files)


def test_collect_files_nonexistent(tmp_path):
    files = collect_files_for_period(tmp_path, "2026", "99")
    assert files == []


def test_generate_digest_with_llm():
    with patch("core.compact.call_llm", return_value="# Дайджест\n\nSummary here"):
        result = generate_digest(["doc 1 content", "doc 2 content"], "kfs", "2026-04")
        assert "Summary" in result or "Дайджест" in result


def test_generate_digest_fallback():
    with patch("core.compact.call_llm", return_value=None):
        result = generate_digest(["doc 1"], "kfs", "2026-04")
        assert "2 документов" in result or "1 документов" in result or "LLM недоступен" in result


def test_compact_month(tmp_path):
    import config
    old_kb = config.KNOWLEDGE_BASE
    config.KNOWLEDGE_BASE = tmp_path

    # Also patch in compact module
    import core.compact
    core.compact.KNOWLEDGE_BASE = tmp_path

    try:
        (tmp_path / "kfs" / "2026" / "03").mkdir(parents=True)
        (tmp_path / "kfs" / "2026" / "03" / "doc.md").write_text("# Test doc\n\nContent here")

        with patch("core.compact.call_llm", return_value="# Digest\n\nSummary"):
            result = compact(project="kfs", period="month", year="2026", month="03")

        assert result["status"] == "completed"
        assert result["files_processed"] == 1
        assert Path(result["digest_path"]).exists()
    finally:
        config.KNOWLEDGE_BASE = old_kb
        core.compact.KNOWLEDGE_BASE = old_kb


def test_compact_no_project(tmp_path):
    import config
    old_kb = config.KNOWLEDGE_BASE
    config.KNOWLEDGE_BASE = tmp_path

    import core.compact
    core.compact.KNOWLEDGE_BASE = tmp_path

    try:
        result = compact(project="nonexistent")
        assert result["status"] == "no_project"
    finally:
        config.KNOWLEDGE_BASE = old_kb
        core.compact.KNOWLEDGE_BASE = old_kb
