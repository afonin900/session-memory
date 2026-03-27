import pytest
from storage.models import LogEntry
from datetime import datetime
from core.noise_filter import should_index_vector


def _entry(role: str, content: str) -> LogEntry:
    return LogEntry(
        agent_type="claude", project="hq", session_id="abc",
        role=role, content=content, timestamp=datetime.now(),
        source_file="test.jsonl",
    )


def test_assistant_passes():
    assert should_index_vector(_entry("assistant", "Вот результат анализа кода")) is True

def test_user_normal_passes():
    assert should_index_vector(_entry("user", "Покажи мне файл config.py и объясни")) is True

def test_tool_use_rejected():
    assert should_index_vector(_entry("tool_use", "Edit file_path=/tmp/foo.py")) is False

def test_system_rejected():
    assert should_index_vector(_entry("system", "[stop_hook_summary]")) is False

def test_user_task_notification_rejected():
    assert should_index_vector(_entry("user", "<task-notification>\n<task-id>abc</task-id>")) is False

def test_user_observed_session_rejected():
    assert should_index_vector(_entry("user", "<observed_from_primary_session>some content</observed_from_primary_session>")) is False

def test_tool_result_short_rejected():
    assert should_index_vector(_entry("tool_result", "OK")) is False

def test_tool_result_long_passes():
    assert should_index_vector(_entry("tool_result", "Error: connection refused to database at localhost:5432, check PostgreSQL is running")) is True

def test_very_short_content_rejected():
    assert should_index_vector(_entry("assistant", ".")) is False
    assert should_index_vector(_entry("assistant", "OK")) is False

def test_system_reminder_rejected():
    assert should_index_vector(_entry("user", "<system-reminder>\nThe task tools haven't been used")) is False
