# core/lifecycle.py — Wake/Sleep/Init lifecycle management
import json
import os
import re
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


LOCK_TIMEOUT_MINUTES = 30


def wake(project: str | None = None, cwd: str | None = None) -> dict:
    """Generate session briefing from SESSION.md.

    Returns dict with:
      - context: str (briefing text for agent)
      - status: str (normal|crash_recovery|new|no_session)
      - session_file: str (path to SESSION.md)
    """
    work_dir = Path(cwd) if cwd else Path.cwd()
    project_name = project or work_dir.name
    session_file = work_dir / ".claude" / "SESSION.md"

    if not session_file.exists():
        return {
            "context": f"No SESSION.md found. Run: sm init --project-name {project_name}",
            "status": "no_session",
            "session_file": str(session_file),
        }

    content = session_file.read_text()

    # Check for crash recovery via status field
    status_match = re.search(r"^status:\s*(.+)$", content, re.MULTILINE)
    current_status = status_match.group(1).strip() if status_match else "unknown"

    if current_status == "in_progress":
        briefing = f"⚠️ CRASH RECOVERY: Предыдущая сессия не завершилась корректно.\n\n{content}"
        result_status = "crash_recovery"
    elif current_status == "new":
        briefing = f"Новый проект. Нет данных предыдущей сессии.\n\n{content}"
        result_status = "new"
    else:
        briefing = content
        result_status = "normal"

    # Set status to in_progress
    new_content = re.sub(
        r"^status:\s*.+$",
        "status: in_progress",
        content,
        count=1,
        flags=re.MULTILINE,
    )
    session_file.write_text(new_content)

    # Create session lock
    lock_file = work_dir / ".claude" / "session.lock"
    lock_data = {
        "pid": os.getpid(),
        "started": datetime.now(timezone.utc).isoformat(),
        "project": project_name,
    }
    lock_file.write_text(json.dumps(lock_data))

    return {
        "context": briefing,
        "status": result_status,
        "session_file": str(session_file),
    }
