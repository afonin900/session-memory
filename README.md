# Session Memory

Search across your AI agent session logs — Claude Code, Codex, Gemini, Aider — by keyword or meaning.

## Quick Start

```bash
pip install lancedb pyarrow sentence-transformers numpy fastmcp
python3 cli.py index           # index all session logs
python3 cli.py search "query"  # keyword search
```

## Architecture

```
cli.py / mcp_server.py
        |
        +-- Indexer (core/indexer.py)
        |       |
        |       +-- parsers/registry.py --> ClaudeParser  (~/.claude/projects/**/*.jsonl)
        |       |                       --> CodexParser   (~/.codex/sessions/rollout-*.jsonl)
        |       |                       --> GeminiParser  (stub)
        |       |                       --> AiderParser   (stub)
        |       |
        |       +-- SqliteFtsStore  (db/sessions.db)   Phase 1: FTS5/BM25
        |       +-- LanceDBStore    (db/vectors/)       Phase 2: embeddings (optional)
        |
        +-- SearchEngine (core/search.py)
                |
                +-- keyword  → FTS5 OR query
                +-- semantic → LanceDB cosine similarity
                +-- all      → RRF merge (Reciprocal Rank Fusion)
                |
                +-- get_context() → SessionFragment (match + 2 messages before/after)
```

Data model: each indexed unit is a `LogEntry` — one message from one session with role, content, timestamp, project alias, and extracted file paths / issue numbers.

## CLI Usage

### Index

```bash
# Full reindex (FTS + vectors if available)
python3 cli.py index

# Incremental — only new or changed files
python3 cli.py index --quick

# Rebuild vectors from existing FTS index (skip re-parsing)
python3 cli.py index --vectors-only
```

### Search

```bash
# Keyword (FTS5, default)
python3 cli.py search "docker migration"

# Semantic (requires vector index)
python3 cli.py search -s "how we solved the memory leak"

# Both merged via RRF
python3 cli.py search -a "authentication flow"

# Filter by project
python3 cli.py search "webhook" -p kfs

# Filter by agent
python3 cli.py search "refactor" --agent codex

# Last 7 days only
python3 cli.py search "deploy" --days 7

# Filter by role (user / assistant / tool_use / tool_result)
python3 cli.py search "issue" --role user

# More results
python3 cli.py search "query" --limit 20
```

### Stats

```bash
python3 cli.py stats
# Total entries: 142831
# By project: kfs: 89012  hq: 31045  jh: 14200 ...
# By agent:   claude: 138000  codex: 4831 ...
```

## MCP Server

Connect session-memory as an MCP tool so Claude Code can search past sessions directly.

Add to `~/.claude/.mcp.json`:

```json
{
  "mcpServers": {
    "session-memory": {
      "type": "stdio",
      "command": "python3",
      "args": ["/absolute/path/to/session-memory/mcp_server.py"]
    }
  }
}
```

Available tool: **`search_sessions`**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | str | required | Search query |
| `project` | str | null | Filter: hq, kfs, jh, bb, aie... |
| `days` | int | 30 | How far back to search |
| `limit` | int | 5 | Max results |

Returns compact results with timestamp, project, session ID, snippet (200 chars), and surrounding context. System messages and entries under 50 chars are filtered out automatically.

Auto-selects RRF mode when vector index is available, falls back to keyword search otherwise.

## Configuration

| Env variable | Default | Description |
|-------------|---------|-------------|
| `SM_DB_DIR` | `./db/` | Directory for SQLite + LanceDB |
| `SM_CLAUDE_LOGS` | `~/.claude/projects/` | Override Claude log path |

Project aliases are defined in `config.py` → `PROJECT_MAP`. Add your repo there if it's not recognized.

## Adding a Parser

1. Create `parsers/yourагент.py` implementing `BaseParser`:

```python
from pathlib import Path
from parsers.base import BaseParser
from storage.models import LogEntry

class YourParser(BaseParser):
    agent_type = "youragent"

    def discover_sessions(self) -> list[Path]:
        base = Path.home() / ".youragent" / "sessions"
        return sorted(base.rglob("*.jsonl")) if base.exists() else []

    def parse_session(self, path: Path) -> list[LogEntry]:
        entries = []
        # Parse path, build LogEntry per message
        # Required fields: agent_type, project, session_id, role, content, timestamp
        return entries
```

2. Register in `parsers/registry.py` → `get_parsers()`:

```python
from parsers.youragent import YourParser

def get_parsers(...) -> list[BaseParser]:
    return [
        ClaudeParser(...),
        CodexParser(),
        YourParser(),   # add here
        ...
    ]
```

3. Run `python3 cli.py index` — your logs will be picked up automatically.

## Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run tests
pytest

# Run tests verbosely
pytest -v
```

- `core/` — indexer, search engine, embedder (no I/O)
- `parsers/` — one file per agent type
- `storage/` — SQLite FTS5 (`sqlite_fts.py`), LanceDB (`lancedb_store.py`), shared models
- `db/` — database files (gitignored)

Requires Python 3.10+. Semantic search downloads `intfloat/multilingual-e5-base` (~400 MB) on first use.
