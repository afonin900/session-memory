from abc import ABC, abstractmethod
from pathlib import Path
from storage.models import LogEntry


class BaseParser(ABC):
    agent_type: str = ""

    @abstractmethod
    def discover_sessions(self) -> list[Path]:
        """Find all log files for this agent type."""

    @abstractmethod
    def parse_session(self, path: Path) -> list[LogEntry]:
        """Parse a single session file into LogEntry list."""
