# core/compact.py — Hippocampus-style memory compaction
import json
import re
from datetime import datetime
from pathlib import Path

from config import KNOWLEDGE_BASE
from core.scrubber import scrub_secrets
from core.llm import call_llm


def collect_files_for_period(
    project_dir: Path, year: str, month: str
) -> list[Path]:
    """Collect all MD files for a given year/month, excluding DIGESTs."""
    target = project_dir / year / month
    if not target.exists():
        return []
    files = sorted(target.glob("*.md"))
    return [f for f in files if "DIGEST" not in f.name.upper()]


def generate_digest(texts: list[str], project: str, period: str) -> str:
    """Generate digest summary via OpenRouter LLM."""
    if not texts:
        return ""

    combined = "\n\n---\n\n".join(texts)
    combined = scrub_secrets(combined)

    # Limit input to ~50K chars (~12K tokens)
    if len(combined) > 50000:
        combined = combined[:50000] + "\n\n[...truncated]"

    prompt = f"""Создай краткий дайджест из этих документов проекта "{project}" за период {period}.

Формат ответа (без markdown code blocks, просто текст):

# Дайджест {project} — {period}

## Ключевые решения
- ...

## Важные факты
- ...

## Уроки
- ...

## Открытые вопросы
- ...

Будь кратким, выдели самое важное. Максимум 500 слов.

Документы:
{combined}"""

    result = call_llm(prompt, max_tokens=1500)

    if result:
        return result

    # Fallback: simple header without LLM
    return f"# Дайджест {project} — {period}\n\n{len(texts)} документов. LLM недоступен для суммаризации.\n"


def compact(
    project: str = "global",
    period: str = "month",
    year: str | None = None,
    month: str | None = None,
) -> dict:
    """Run Hippocampus compaction for a project.

    Returns: dict with status, digest_path, files_processed
    """
    now = datetime.now()
    y = year or str(now.year)

    project_dir = KNOWLEDGE_BASE / project
    if not project_dir.exists():
        return {"status": "no_project", "message": f"No ~/Knowledge/{project}/ directory"}

    if period == "month":
        if month:
            m = month
        else:
            prev_month = now.month - 1 if now.month > 1 else 12
            m = f"{prev_month:02d}"
            if now.month == 1 and not year:
                y = str(now.year - 1)

        files = collect_files_for_period(project_dir, y, m)
        if not files:
            return {"status": "no_files", "message": f"No files for {y}/{m}"}

        texts = [f.read_text(errors="replace") for f in files]
        digest = generate_digest(texts, project, f"{y}-{m}")

        digest_path = project_dir / y / m / f"DIGEST-{y}-{m}.md"
        digest_path.parent.mkdir(parents=True, exist_ok=True)
        digest_path.write_text(f"""---
title: Дайджест {project} за {y}-{m}
type: doc
project: {project}
date: {y}-{m}-01
tags: [digest, auto-generated]
importance: high
---

{digest}
""")

        return {
            "status": "completed",
            "digest_path": str(digest_path),
            "files_processed": len(files),
        }

    elif period == "quarter":
        q_month = int(month or str(now.month))
        q_start = ((q_month - 1) // 3) * 3 + 1
        months = [f"{m:02d}" for m in range(q_start, q_start + 3)]

        digest_texts = []
        for m in months:
            digest_file = project_dir / y / m / f"DIGEST-{y}-{m}.md"
            if digest_file.exists():
                digest_texts.append(digest_file.read_text(errors="replace"))

        if not digest_texts:
            return {"status": "no_digests", "message": "No monthly digests found for quarter"}

        q_num = (q_start - 1) // 3 + 1
        root = generate_digest(digest_texts, project, f"Q{q_num} {y}")

        root_path = project_dir / y / f"ROOT-Q{q_num}-{y}.md"
        root_path.parent.mkdir(parents=True, exist_ok=True)
        root_path.write_text(f"""---
title: ROOT {project} Q{q_num} {y}
type: doc
project: {project}
date: {y}-{months[0]}-01
tags: [root, quarterly, auto-generated]
importance: high
---

{root}
""")

        return {
            "status": "completed",
            "digest_path": str(root_path),
            "files_processed": len(digest_texts),
        }

    return {"status": "unknown_period"}
