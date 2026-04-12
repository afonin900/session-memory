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

## v2.0 Commands

```bash
# Lifecycle (auto via hooks)
python3 cli.py init --profile content --project-name kfs
python3 cli.py wake                    # session start briefing
python3 cli.py sleep --transcript X    # session end, save state

# Knowledge Base
python3 cli.py index --knowledge       # index ~/Knowledge/ MD files
python3 cli.py observe transcript.jsonl           # extract facts (regex)
python3 cli.py observe transcript.jsonl --full     # extract via LLM (OpenRouter)
python3 cli.py observe transcript.jsonl --save     # save to ~/Knowledge/
python3 cli.py compact -p kfs                      # monthly digest
python3 cli.py compact -p kfs --period quarter     # quarterly ROOT

# Graph
python3 cli.py graph --build           # build wiki-links graph
python3 cli.py graph --related /path   # find related docs

# Diagnostics
python3 cli.py stats                   # sessions + knowledge + lifecycle
python3 cli.py status                  # hooks, SESSION.md, db check

# Search (enhanced)
python3 cli.py search -a "query" --type decision --since 30d
```

## Architecture

- `cli.py` — thin argparse entry point
- `core/` — business logic (indexer, search, embedder, lifecycle, observe, compact, graph, llm)
- `parsers/` — pluggable log parsers (claude, codex, gemini, aider)
- `storage/` — SQLite FTS5 + LanceDB

## Adding a New Parser

1. Create `parsers/newagent.py` implementing `BaseParser`
2. Add to `parsers/registry.py` `get_parsers()` function

## Environment Variables

- `SM_DB_DIR` — override database directory (default: `./db/`)
- `SM_CLAUDE_LOGS` — override Claude logs path (default: `~/.claude/projects/`)
- `OPENROUTER_API_KEY` — for observe --full and compact (fallback: reads from ~/Github/ai-corporation-kfs/.env)

## Dependencies

```bash
pip install -r requirements.txt
```

Requires: Python 3.10+, ONNX Runtime for fast inference (~265MB exported model, one-time setup via `scripts/export_onnx.py`). Falls back to PyTorch/sentence-transformers if ONNX model not exported.
