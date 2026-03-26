# storage/models.py
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class LogEntry:
    agent_type: str          # claude, codex, gemini, aider
    project: str             # kfs, jh, hq, bb, aie, sm
    session_id: str          # UUID
    role: str                # user, assistant, tool_use, tool_result, system
    content: str             # text content
    timestamp: datetime
    file_paths: list[str] = field(default_factory=list)
    issue_numbers: list[str] = field(default_factory=list)
    source_file: str = ""


@dataclass
class SearchResult:
    id: int
    agent_type: str
    project: str
    session_id: str
    role: str
    content: str
    timestamp: datetime
    file_paths: list[str]
    issue_numbers: list[str]
    score: float = 0.0


@dataclass
class SessionFragment:
    match: SearchResult
    before: list[SearchResult]
    after: list[SearchResult]
    session_id: str
    project: str
