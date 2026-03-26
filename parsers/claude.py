import json
import re
from datetime import datetime, timezone
from pathlib import Path

from config import CLAUDE_LOGS_BASE, TOOL_RESULT_MAX_LENGTH, extract_project
from parsers.base import BaseParser
from storage.models import LogEntry

_PROCESS_TYPES = {"user", "assistant", "system"}
_FILE_TOOLS = {"Read", "Write", "Edit", "Glob", "Grep"}
_FILE_PARAMS = {"file_path", "path", "pattern"}
_ISSUE_RE = re.compile(r"#(\d+)")


def _extract_issues(text: str) -> list[str]:
    return list(set(_ISSUE_RE.findall(text)))


def _extract_file_paths_from_tool(tool_input: dict, tool_name: str) -> list[str]:
    if tool_name not in _FILE_TOOLS:
        return []
    paths = []
    for param in _FILE_PARAMS:
        if param in tool_input and isinstance(tool_input[param], str):
            paths.append(tool_input[param])
    return paths


def _parse_assistant_content(content_blocks: list, cwd: str) -> list[dict]:
    results = []
    text_parts = []
    all_file_paths = []

    for block in content_blocks:
        btype = block.get("type", "")
        if btype == "thinking":
            continue
        elif btype == "text":
            text = block.get("text", "")
            if text.strip():
                text_parts.append(text)
        elif btype == "tool_use":
            tool_name = block.get("name", "")
            tool_input = block.get("input", {})
            file_paths = _extract_file_paths_from_tool(tool_input, tool_name)
            all_file_paths.extend(file_paths)
            summary_parts = [tool_name]
            for param in ("file_path", "path", "pattern", "query", "command", "skill"):
                if param in tool_input:
                    val = str(tool_input[param])
                    if len(val) > 100:
                        val = val[:100] + "..."
                    summary_parts.append(f"{param}={val}")
            tool_summary = " ".join(summary_parts)
            results.append({
                "role": "tool_use",
                "content": tool_summary,
                "file_paths": file_paths,
                "issue_numbers": _extract_issues(tool_summary),
            })

    if text_parts:
        combined = "\n".join(text_parts)
        results.insert(0, {
            "role": "assistant",
            "content": combined,
            "file_paths": all_file_paths,
            "issue_numbers": _extract_issues(combined),
        })

    return results


def _parse_user_content(message: dict) -> list[dict]:
    content = message.get("content", "")

    if isinstance(content, str):
        return [{
            "role": "user",
            "content": content,
            "file_paths": [],
            "issue_numbers": _extract_issues(content),
        }]

    results = []
    for block in content:
        btype = block.get("type", "")
        if btype == "text":
            text = block.get("text", "")
            if text.strip():
                results.append({
                    "role": "user",
                    "content": text,
                    "file_paths": [],
                    "issue_numbers": _extract_issues(text),
                })
        elif btype == "tool_result":
            tr_content = block.get("content", "")
            if isinstance(tr_content, str):
                truncated = tr_content[:TOOL_RESULT_MAX_LENGTH]
            elif isinstance(tr_content, list):
                text_parts = [b.get("text", "") for b in tr_content
                              if isinstance(b, dict) and b.get("type") == "text"]
                truncated = " ".join(text_parts)[:TOOL_RESULT_MAX_LENGTH]
            else:
                truncated = ""
            if truncated.strip():
                results.append({
                    "role": "tool_result",
                    "content": truncated,
                    "file_paths": [],
                    "issue_numbers": _extract_issues(truncated),
                })

    return results


class ClaudeParser(BaseParser):
    agent_type = "claude"

    def __init__(self, logs_base: Path | None = None):
        self.logs_base = logs_base or CLAUDE_LOGS_BASE

    def discover_sessions(self) -> list[Path]:
        if not self.logs_base.exists():
            return []
        return sorted(self.logs_base.rglob("*.jsonl"))

    def parse_session(self, path: Path) -> list[LogEntry]:
        entries = []
        session_id = path.stem

        with open(path, "r", encoding="utf-8") as f:
            for line_str in f:
                line_str = line_str.strip()
                if not line_str:
                    continue
                try:
                    line = json.loads(line_str)
                except json.JSONDecodeError:
                    continue

                event_type = line.get("type", "")
                if event_type not in _PROCESS_TYPES:
                    continue

                cwd = line.get("cwd", "")
                project = extract_project(cwd)
                ts_str = line.get("timestamp", "")
                try:
                    timestamp = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    timestamp = datetime.now(timezone.utc)

                sid = line.get("sessionId", session_id)
                message = line.get("message", {})

                if event_type == "assistant":
                    content_blocks = message.get("content", [])
                    if isinstance(content_blocks, list):
                        parsed = _parse_assistant_content(content_blocks, cwd)
                        for p in parsed:
                            entries.append(LogEntry(
                                agent_type=self.agent_type,
                                project=project,
                                session_id=sid,
                                role=p["role"],
                                content=p["content"],
                                timestamp=timestamp,
                                file_paths=p["file_paths"],
                                issue_numbers=p["issue_numbers"],
                                source_file=str(path),
                            ))

                elif event_type == "user":
                    if line.get("isMeta"):
                        continue
                    parsed = _parse_user_content(message)
                    for p in parsed:
                        entries.append(LogEntry(
                            agent_type=self.agent_type,
                            project=project,
                            session_id=sid,
                            role=p["role"],
                            content=p["content"],
                            timestamp=timestamp,
                            file_paths=p["file_paths"],
                            issue_numbers=p["issue_numbers"],
                            source_file=str(path),
                        ))

                elif event_type == "system":
                    subtype = line.get("subtype", "system")
                    content = f"[{subtype}]"
                    entries.append(LogEntry(
                        agent_type=self.agent_type,
                        project=project,
                        session_id=sid,
                        role="system",
                        content=content,
                        timestamp=timestamp,
                        source_file=str(path),
                    ))

        return entries
