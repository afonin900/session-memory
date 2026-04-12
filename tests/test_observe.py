import json
import pytest
from pathlib import Path
from core.observe import observe_fast, save_facts_to_knowledge


def _make_transcript(messages: list[dict], path: Path):
    with open(path, "w") as f:
        for msg in messages:
            f.write(json.dumps({"message": {"role": msg.get("role", "assistant"), "content": msg["content"]}}) + "\n")


def test_observe_fast_extracts_decisions(tmp_path):
    transcript = tmp_path / "transcript.jsonl"
    _make_transcript([
        {"content": "Решение: используем 3 канала — Instagram, Telegram, VK для маркетинга"},
        {"content": "Факт: конверсия на лендинге составляет 2.3% за последний месяц"},
        {"content": "Урок: не запускать рекламу в пятницу вечером, CTR падает значительно"},
    ], transcript)

    facts = observe_fast(str(transcript), project="kfs")
    assert len(facts) >= 2
    types = [f["type"] for f in facts]
    assert "decision" in types


def test_observe_fast_empty_transcript(tmp_path):
    transcript = tmp_path / "empty.jsonl"
    transcript.write_text("")
    facts = observe_fast(str(transcript), project="test")
    assert facts == []


def test_observe_fast_scrubs_secrets(tmp_path):
    transcript = tmp_path / "secret.jsonl"
    _make_transcript([
        {"content": "Решение: API ключ sk-ant-api03-abc123def456ghijklmnop для аутентификации"},
    ], transcript)

    facts = observe_fast(str(transcript), project="test")
    for f in facts:
        assert "sk-ant-api03" not in f["content"]


def test_observe_fast_nonexistent_file():
    facts = observe_fast("/nonexistent/path.jsonl", project="test")
    assert facts == []


def test_save_facts_to_knowledge(tmp_path):
    import core.observe
    original = core.observe.KNOWLEDGE_BASE
    # Temporarily override KNOWLEDGE_BASE
    import config
    old_kb = config.KNOWLEDGE_BASE
    config.KNOWLEDGE_BASE = tmp_path
    core.observe.KNOWLEDGE_BASE = tmp_path

    try:
        facts = [
            {"type": "decision", "content": "Use three channels for marketing", "date": "2026-04-12", "project": "kfs", "source": "test"},
        ]
        saved = save_facts_to_knowledge(facts)
        assert saved == 1

        # Check file was created
        files = list(tmp_path.rglob("*.md"))
        assert len(files) == 1
        content = files[0].read_text()
        assert "Use three channels" in content
        assert "decision" in content

        # Re-save should skip (idempotent)
        saved2 = save_facts_to_knowledge(facts)
        assert saved2 == 0
    finally:
        config.KNOWLEDGE_BASE = old_kb
        core.observe.KNOWLEDGE_BASE = original
