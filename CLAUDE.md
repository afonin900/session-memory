# Session Memory

Cross-project CLI tool for searching AI agent session logs.

## Quick Start

```bash
pip install -r requirements.txt
python3 scripts/export_onnx.py   # one-time: export model to ONNX (~265MB)
python3 cli.py index              # index session logs
python3 cli.py search "query"     # keyword search
python3 cli.py search -s "query"  # semantic search
python3 cli.py search -a "query"  # both merged (RRF)
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
pip install -r requirements.txt
```

Requires: Python 3.10+, ONNX Runtime for fast inference (~265MB exported model, one-time setup via `scripts/export_onnx.py`). Falls back to PyTorch/sentence-transformers if ONNX model not exported.
