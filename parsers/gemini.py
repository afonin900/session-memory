from pathlib import Path
from parsers.base import BaseParser
from storage.models import LogEntry


class GeminiParser(BaseParser):
    agent_type = "gemini"

    def discover_sessions(self) -> list[Path]:
        return []

    def parse_session(self, path: Path) -> list[LogEntry]:
        return []
