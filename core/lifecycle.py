# core/lifecycle.py — Wake/Sleep/Init lifecycle management
import json
import os
from datetime import datetime, timezone
from pathlib import Path

KNOWLEDGE_BASE = Path.home() / "Knowledge"

SESSION_TEMPLATE = """# Session State

## Status
status: new

## Последняя сессия
- **Дата:** —
- **Session ID:** —
- **Что сделано:** —
- **Что не закончено:** —
- **Следующий шаг:** —

## Ключевые решения (последние 10)
—

## Открытые задачи
—
"""

BACKLOG_TEMPLATE = """# Backlog

## В работе
—

## Запланировано
—

## Идеи
—
"""

CONTENT_MAP_TEMPLATE = """# Content Map

## Каналы
—

## Форматы
—

## Расписание
—
"""

ARCHITECTURE_TEMPLATE = """# Architecture

## Стек
—

## Структура
—
"""


def init_project(project_name: str, profile: str = "software") -> dict:
    """Initialize session-memory in current project."""
    claude_dir = Path.cwd() / ".claude"
    claude_dir.mkdir(exist_ok=True)

    results = {"created": [], "skipped": []}

    # SESSION.md
    session_path = claude_dir / "SESSION.md"
    if not session_path.exists():
        session_path.write_text(SESSION_TEMPLATE)
        results["created"].append(str(session_path))
    else:
        results["skipped"].append(str(session_path))

    # BACKLOG.md
    backlog_path = claude_dir / "BACKLOG.md"
    if not backlog_path.exists():
        backlog_path.write_text(BACKLOG_TEMPLATE)
        results["created"].append(str(backlog_path))
    else:
        results["skipped"].append(str(backlog_path))

    # Profile-specific file
    if profile == "content":
        map_path = claude_dir / "CONTENT-MAP.md"
        if not map_path.exists():
            map_path.write_text(CONTENT_MAP_TEMPLATE)
            results["created"].append(str(map_path))
        else:
            results["skipped"].append(str(map_path))
    else:
        arch_path = claude_dir / "ARCHITECTURE.md"
        if not arch_path.exists():
            arch_path.write_text(ARCHITECTURE_TEMPLATE)
            results["created"].append(str(arch_path))
        else:
            results["skipped"].append(str(arch_path))

    # Knowledge directory
    kb_dir = KNOWLEDGE_BASE / project_name
    kb_dir.mkdir(parents=True, exist_ok=True)
    results["knowledge_dir"] = str(kb_dir)

    return results
