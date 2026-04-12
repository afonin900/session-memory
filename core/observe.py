# core/observe.py — Fact extraction from session transcripts
import json
import re
from datetime import datetime
from pathlib import Path

from core.scrubber import scrub_secrets
from config import KNOWLEDGE_BASE


# Regex patterns for fact extraction
_DECISION_PATTERNS = [
    re.compile(r"(?:решили|решение:|decided|decision:)\s*(.{10,200})", re.IGNORECASE),
]
_FACT_PATTERNS = [
    re.compile(r"(?:факт:|fact:|выяснил[иа]?|обнаружил[иа]?)\s*(.{10,200})", re.IGNORECASE),
]
_LESSON_PATTERNS = [
    re.compile(r"(?:урок:|lesson:|вывод:|takeaway:)\s*(.{10,200})", re.IGNORECASE),
]


def observe_fast(transcript_path: str, project: str = "global") -> list[dict]:
    """Extract facts from transcript using regex heuristics (no LLM).

    Returns list of dicts: {type, content, source, date, project}
    """
    path = Path(transcript_path)
    if not path.exists() or path.stat().st_size == 0:
        return []

    try:
        file_size = path.stat().st_size
        max_bytes = 524288  # 500KB max
        with open(path, "rb") as f:
            if file_size > max_bytes:
                f.seek(-max_bytes, 2)
                f.readline()
            raw = f.read().decode("utf-8", errors="replace")
    except OSError:
        return []

    lines = raw.strip().split("\n")
    facts = []
    seen = set()
    today = datetime.now().strftime("%Y-%m-%d")

    for line in lines:
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue

        msg = entry.get("message", entry)
        if isinstance(msg, dict):
            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    b.get("text", "") for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                )
        elif isinstance(msg, str):
            content = msg
        else:
            continue

        if not content or len(content) < 15:
            continue

        content = scrub_secrets(content)

        for pattern in _DECISION_PATTERNS:
            m = pattern.search(content)
            if m:
                text = m.group(1).strip().rstrip(".")
                if text not in seen:
                    seen.add(text)
                    facts.append({"type": "decision", "content": text, "source": transcript_path, "date": today, "project": project})

        for pattern in _FACT_PATTERNS:
            m = pattern.search(content)
            if m:
                text = m.group(1).strip().rstrip(".")
                if text not in seen:
                    seen.add(text)
                    facts.append({"type": "fact", "content": text, "source": transcript_path, "date": today, "project": project})

        for pattern in _LESSON_PATTERNS:
            m = pattern.search(content)
            if m:
                text = m.group(1).strip().rstrip(".")
                if text not in seen:
                    seen.add(text)
                    facts.append({"type": "lesson", "content": text, "source": transcript_path, "date": today, "project": project})

    return facts


_OBSERVE_PROMPT = """Извлеки факты, решения и уроки из этого лога сессии AI-агента.

Для каждого найденного элемента верни JSON объект с полями:
- type: "decision" | "fact" | "lesson"
- content: краткая формулировка (1-2 предложения, на языке оригинала)

Верни ТОЛЬКО JSON массив, без комментариев и markdown:
[{"type": "decision", "content": "..."}, ...]

Если ничего не найдено — верни пустой массив: []

Лог сессии:
"""


def observe_full(transcript_path: str, project: str = "global") -> list[dict]:
    """Extract facts from transcript using LLM via OpenRouter.

    Falls back to observe_fast if LLM unavailable.
    """
    path = Path(transcript_path)
    if not path.exists() or path.stat().st_size == 0:
        return []

    # Read and scrub transcript
    try:
        file_size = path.stat().st_size
        max_bytes = 100_000  # ~25K tokens
        with open(path, "rb") as f:
            if file_size > max_bytes:
                f.seek(-max_bytes, 2)
                f.readline()
            raw = f.read().decode("utf-8", errors="replace")
    except OSError:
        return []

    raw = scrub_secrets(raw)

    # Call LLM
    from core.llm import call_llm
    response = call_llm(_OBSERVE_PROMPT + raw)

    if not response:
        return observe_fast(transcript_path, project)

    # Parse response
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        # Extract JSON array from response
        match = re.search(r"\[.*\]", response, re.DOTALL)
        if not match:
            return observe_fast(transcript_path, project)
        items = json.loads(match.group())
    except (json.JSONDecodeError, ValueError):
        return observe_fast(transcript_path, project)

    facts = []
    for item in items:
        if not isinstance(item, dict):
            continue
        fact_type = item.get("type", "fact")
        fact_content = item.get("content", "")
        if fact_type in ("decision", "fact", "lesson") and len(fact_content) > 10:
            facts.append({
                "type": fact_type,
                "content": scrub_secrets(fact_content),
                "source": transcript_path,
                "date": today,
                "project": project,
            })

    return facts


def save_facts_to_knowledge(facts: list[dict]) -> int:
    """Save extracted facts as MD files in ~/Knowledge/{project}/."""
    saved = 0
    for fact in facts:
        project = fact.get("project", "global")
        date = fact.get("date", datetime.now().strftime("%Y-%m-%d"))
        year, month = date[:4], date[5:7]

        target_dir = KNOWLEDGE_BASE / project / year / month
        target_dir.mkdir(parents=True, exist_ok=True)

        slug = re.sub(r"[^\w\s-]", "", fact["content"][:40]).strip().replace(" ", "-").lower()
        if not slug:
            slug = "fact"
        filename = f"{date[:10]}-{fact['type']}-{slug}.md"
        filepath = target_dir / filename

        if filepath.exists():
            continue

        content = f"""---
title: {fact['content'][:80]}
type: {fact['type']}
project: {project}
date: {date}
tags: [auto-extracted]
importance: medium
---

{fact['content']}

---
*Source: {fact.get('source', 'unknown')}*
"""
        filepath.write_text(content)
        saved += 1

    return saved
