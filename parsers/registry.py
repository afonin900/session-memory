from pathlib import Path
from typing import Iterator
from parsers.base import BaseParser
from parsers.claude import ClaudeParser


def get_parsers(claude_logs_base: Path | None = None) -> list[BaseParser]:
    """Factory: build parser list with optional overrides."""
    return [
        ClaudeParser(logs_base=claude_logs_base),
    ]


def discover_all(parsers: list[BaseParser] | None = None) -> Iterator[tuple[BaseParser, Path]]:
    """Discover all session files from all parsers."""
    for parser in (parsers or get_parsers()):
        for path in parser.discover_sessions():
            yield parser, path
