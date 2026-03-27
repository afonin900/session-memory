# Session Memory

Cross-project CLI tool for searching AI agent session logs.

## Quick Start

```bash
python3 cli.py index          # Index all session logs
python3 cli.py search "query" # Keyword search (FTS5)
python3 cli.py search -s "query"  # Semantic search (LanceDB)
python3 cli.py search -a "query"  # Both merged (RRF)
python3 cli.py stats          # Index statistics
```

## MCP Server

Session Memory доступен как MCP tool для Claude Code:

```bash
# Настройка в ~/.claude/settings.json
{
  "mcpServers": {
    "session-memory": {
      "command": "python3",
      "args": ["/path/to/session-memory/mcp_server.py"]
    }
  }
}
```

Tool `search_sessions`: поиск по логам сессий (keyword + semantic RRF merge).

## Architecture

- `cli.py` — thin argparse entry point
- `core/` — business logic (indexer, search, embedder)
- `parsers/` — pluggable log parsers (claude, codex, gemini, aider)
- `storage/` — SQLite FTS5 + LanceDB

## Adding a New Parser

1. Create `parsers/newagent.py` implementing `BaseParser`
2. Add to `parsers/registry.py` `get_parsers()` function

## Environment Variables

- `SM_DB_DIR` — override database directory (default: `./db/`)
- `SM_CLAUDE_LOGS` — override Claude logs path (default: `~/.claude/projects/`)

## Dependencies

```bash
pip install lancedb pyarrow sentence-transformers numpy
```

Requires: Python 3.10+, ~400MB for multilingual-e5-base model (downloaded on first semantic search)
