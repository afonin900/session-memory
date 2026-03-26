from pathlib import Path
from parsers.base import BaseParser
from storage.models import LogEntry


class AiderParser(BaseParser):
    agent_type = "aider"

    def discover_sessions(self) -> list[Path]:
        return []

    def parse_session(self, path: Path) -> list[LogEntry]:
        return []
