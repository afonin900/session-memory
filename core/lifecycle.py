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

    # Sanitize project name (Fix 1: path traversal protection)
    safe_name = Path(project_name).name
    if not safe_name or safe_name.startswith('.'):
        return {"created": [], "skipped": [], "error": f"Invalid project name: {project_name!r}"}

    # Knowledge directory
    kb_dir = KNOWLEDGE_BASE / safe_name
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

    # Check existing lock and clean up corrupted ones (Fix 6: LOCK_TIMEOUT_MINUTES)
    lock_file = work_dir / ".claude" / "session.lock"
    if lock_file.exists():
        try:
            lock_data_existing = json.loads(lock_file.read_text())
            lock_time = datetime.fromisoformat(lock_data_existing["started"])
            age_minutes = (datetime.now(timezone.utc) - lock_time).total_seconds() / 60
            if age_minutes < LOCK_TIMEOUT_MINUTES:
                # Active session exists
                pass  # Will be detected by status: in_progress anyway
        except (json.JSONDecodeError, KeyError, ValueError):
            lock_file.unlink()  # corrupted lock, remove

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


MAX_DECISIONS = 10


def _extract_from_transcript(transcript_path: str, last_n: int = 50) -> dict:
    """Extract summary from last N messages of transcript JSONL.

    Uses regex heuristics, no LLM calls.
    Returns: {done: [], not_done: [], decisions: [], next_step: str}
    """
    result = {"done": [], "not_done": [], "decisions": [], "next_step": ""}

    if not transcript_path or not Path(transcript_path).exists():
        return result

    try:
        file_path = Path(transcript_path)
        file_size = file_path.stat().st_size
        max_bytes = 524288  # 500KB max

        with open(file_path, 'rb') as f:
            if file_size > max_bytes:
                f.seek(-max_bytes, 2)
                f.readline()  # skip partial first line
            content = f.read().decode('utf-8', errors='replace')
        lines = content.strip().split("\n")
    except (OSError, UnicodeDecodeError):
        return result

    recent = lines[-last_n:] if len(lines) > last_n else lines

    for line in recent:
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue

        # Handle different transcript formats
        content = ""
        msg = entry.get("message", entry)
        if isinstance(msg, dict):
            c = msg.get("content", "")
            if isinstance(c, str):
                content = c
            elif isinstance(c, list):
                content = " ".join(
                    block.get("text", "") for block in c
                    if isinstance(block, dict) and block.get("type") == "text"
                )
        elif isinstance(msg, str):
            content = msg

        if not content or len(content) < 10:
            continue

        lower = content.lower()

        # Extract decisions
        if any(w in lower for w in ["решили", "решение:", "decided", "decision:"]):
            snippet = content[:150].replace("\n", " ").strip()
            if snippet not in result["decisions"]:
                result["decisions"].append(snippet)

        # Extract not done / TODO
        if any(w in lower for w in ["не закончил", "todo", "не успел", "осталось", "не готово", "нужно ещё"]):
            snippet = content[:150].replace("\n", " ").strip()
            if snippet not in result["not_done"]:
                result["not_done"].append(snippet)

        # Extract done
        if any(w in lower for w in ["готово", "сделано", "completed", "done", "закоммитил", "запушил", "реализовал"]):
            snippet = content[:150].replace("\n", " ").strip()
            if snippet not in result["done"]:
                result["done"].append(snippet)

    return result


def sleep(
    project: str | None = None,
    cwd: str | None = None,
    transcript_path: str | None = None,
    summary: str | None = None,
    session_id: str | None = None,
) -> dict:
    """Finalize session: update SESSION.md, remove lock.

    Returns dict with status and what was updated.
    """
    work_dir = Path(cwd) if cwd else Path.cwd()
    project_name = project or work_dir.name
    session_file = work_dir / ".claude" / "SESSION.md"
    lock_file = work_dir / ".claude" / "session.lock"

    if not session_file.exists():
        return {"status": "no_session", "message": "No SESSION.md found"}

    content = session_file.read_text()

    # Check idempotency (Fix 4: stricter check)
    if session_id and f"**Session ID:** {session_id}" in content:
        return {"status": "already_processed", "message": f"Session {session_id[:8]} already saved"}

    # Extract from transcript if available
    extracted = _extract_from_transcript(transcript_path)

    # Build new SESSION.md
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sid = session_id or "unknown"

    done_items = extracted["done"][:5] or ["—"]
    done_lines = "\n".join(f"  - {d}" for d in done_items)

    not_done_items = extracted["not_done"][:5] or ["—"]
    not_done_lines = "\n".join(f"  - {d}" for d in not_done_items)

    next_step = not_done_items[0] if not_done_items[0] != "—" else "—"

    # Preserve existing decisions, add new, keep last MAX_DECISIONS
    existing_decisions = re.findall(
        r"^- \d{4}-\d{2}-\d{2}:.*$", content, re.MULTILINE
    )
    date_prefix = datetime.now().strftime("%Y-%m-%d")
    new_decisions = [
        f"- {date_prefix}: {d}"
        for d in extracted["decisions"][:3]
    ]
    all_decisions = (new_decisions + existing_decisions)[:MAX_DECISIONS]
    decisions_text = "\n".join(all_decisions) if all_decisions else "—"

    # Preserve existing unchecked tasks + add new ones (Fix 5: idempotent tasks)
    existing_tasks = re.findall(r"^- \[ \] .+$", content, re.MULTILINE)
    new_tasks = [f"- [ ] {t}" for t in extracted["not_done"][:10]] if extracted["not_done"] else []
    all_tasks = list(dict.fromkeys(new_tasks + existing_tasks))[:15]  # dedup, max 15
    tasks_text = "\n".join(all_tasks) if all_tasks else "—"

    new_content = f"""# Session State

## Status
status: completed

## Последняя сессия
- **Дата:** {now}
- **Session ID:** {sid}
- **Что сделано:**
{done_lines}
- **Что не закончено:**
{not_done_lines}
- **Следующий шаг:**
  - {next_step}

## Ключевые решения (последние {MAX_DECISIONS})
{decisions_text}

## Открытые задачи
{tasks_text}
"""

    # If user provided explicit summary, insert after Status (Fix 3: safe insertion)
    if summary:
        new_content = new_content.replace(
            "## Последняя сессия",
            f"## Summary\n{summary.replace('#', '').strip()}\n\n## Последняя сессия",
            1,  # only first occurrence
        )

    session_file.write_text(new_content)

    # Remove lock
    if lock_file.exists():
        lock_file.unlink()

    return {
        "status": "completed",
        "session_file": str(session_file),
        "extracted": {
            "done": len(extracted["done"]),
            "not_done": len(extracted["not_done"]),
            "decisions": len(extracted["decisions"]),
        },
    }
