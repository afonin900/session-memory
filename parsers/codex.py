import json
import re
from datetime import datetime, timezone
from pathlib import Path

from config import CODEX_LOGS_BASE, TOOL_RESULT_MAX_LENGTH, extract_project
from parsers.base import BaseParser
from storage.models import LogEntry

_ISSUE_RE = re.compile(r"#(\d+)")

# Role mapping: Codex uses "developer" for user input
_ROLE_MAP = {
    "developer": "user",
    "user": "user",
    "assistant": "assistant",
    "system": "system",
}


class CodexParser(BaseParser):
    agent_type = "codex"

    def __init__(self, logs_base: Path | None = None):
        self.logs_base = logs_base or CODEX_LOGS_BASE

    def discover_sessions(self) -> list[Path]:
        if not self.logs_base.exists():
            return []
        return sorted(self.logs_base.rglob("rollout-*.jsonl"))

    def parse_session(self, path: Path) -> list[LogEntry]:
        entries = []
        session_id = ""
        cwd = ""
        project = "unknown"

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
                ts_str = line.get("timestamp", "")
                try:
                    timestamp = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    timestamp = datetime.now(timezone.utc)

                payload = line.get("payload", {})

                if event_type == "session_meta":
                    session_id = payload.get("id", path.stem)
                    cwd = payload.get("cwd", "")
                    project = extract_project(cwd)
                    continue

                if event_type == "response_item":
                    p_type = payload.get("type", "")

                    if p_type == "message":
                        role = _ROLE_MAP.get(payload.get("role", ""), "system")
                        content_blocks = payload.get("content", [])
                        text_parts = []
                        for block in content_blocks:
                            for key in ("text", "input_text", "output_text"):
                                if key in block:
                                    text_parts.append(block[key])
                        content = "\n".join(text_parts)
                        if content.strip():
                            entries.append(LogEntry(
                                agent_type=self.agent_type,
                                project=project,
                                session_id=session_id,
                                role=role,
                                content=content,
                                timestamp=timestamp,
                                file_paths=[],
                                issue_numbers=_ISSUE_RE.findall(content),
                                source_file=str(path),
                            ))

                    elif p_type == "function_call":
                        fn_name = payload.get("name", "")
                        fn_args = payload.get("arguments", "")
                        summary = f"{fn_name} {fn_args[:100]}"
                        entries.append(LogEntry(
                            agent_type=self.agent_type,
                            project=project,
                            session_id=session_id,
                            role="tool_use",
                            content=summary,
                            timestamp=timestamp,
                            file_paths=[],
                            issue_numbers=[],
                            source_file=str(path),
                        ))

                    elif p_type == "function_call_output":
                        output = payload.get("output", "")
                        truncated = output[:TOOL_RESULT_MAX_LENGTH]
                        entries.append(LogEntry(
                            agent_type=self.agent_type,
                            project=project,
                            session_id=session_id,
                            role="tool_result",
                            content=truncated,
                            timestamp=timestamp,
                            file_paths=[],
                            issue_numbers=[],
                            source_file=str(path),
                        ))

                # Skip event_msg and turn_context — not useful for search

        return entries
