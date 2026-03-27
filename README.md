# Session Memory

**[English](#english) | [Русский](#русский)**

---

## English

Search across your AI agent session logs — Claude Code, Codex, Gemini, Aider — by keyword or meaning.

### What's New in v0.2

- **10x faster cold start** — ONNX Runtime replaces PyTorch (0.8s vs 3s)
- **Noise filter** — 42% less noise in semantic search (tool_use, system messages filtered from vectors)
- **FTS5 fix** — special characters (hyphens, %, *, ^) no longer crash keyword search
- **MCP server** — search sessions directly from Claude Code

### Quick Start

```bash
pip install -r requirements.txt
python3 scripts/export_onnx.py   # one-time: export model to ONNX (~265MB)
python3 cli.py index              # index all session logs
python3 cli.py search "query"     # keyword search
```

### Architecture

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
                +-- keyword  -> FTS5 OR query
                +-- semantic -> LanceDB cosine similarity
                +-- all      -> RRF merge (Reciprocal Rank Fusion)
                |
                +-- get_context() -> SessionFragment (match + 2 messages before/after)
```

**Data model:** each indexed unit is a `LogEntry` — one message from one session with role, content, timestamp, project alias, and extracted file paths / issue numbers.

### CLI Usage

#### Index

```bash
# Full reindex (FTS + vectors if available)
python3 cli.py index

# Incremental — only new or changed files
python3 cli.py index --quick

# Rebuild vectors from existing FTS index (skip re-parsing)
python3 cli.py index --vectors-only

# Limit RSS memory ceiling during vector indexing (default: 1024 MB)
python3 cli.py index --max-memory 2048
```

#### Search

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

#### Stats

```bash
python3 cli.py stats
# Total entries: 142831
# By project: kfs: 89012  hq: 31045  jh: 14200 ...
# By agent:   claude: 138000  codex: 4831 ...
```

### MCP Server

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

### Configuration

| Env variable | Default | Description |
|-------------|---------|-------------|
| `SM_DB_DIR` | `./db/` | Directory for SQLite + LanceDB |
| `SM_CLAUDE_LOGS` | `~/.claude/projects/` | Override Claude log path |

Project aliases are defined in `config.py` → `PROJECT_MAP`. Add your repo there if it's not recognized.

### Adding a Parser

1. Create `parsers/youragent.py` implementing `BaseParser`:

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

### Development

```bash
# Install dependencies (ONNX Runtime, LanceDB, fastmcp)
pip install -r requirements.txt

# Run tests
pytest

# Run tests verbosely
pytest -v
```

Project structure:

- `core/` — indexer, search engine, embedder (no I/O)
- `parsers/` — one file per agent type
- `storage/` — SQLite FTS5 (`sqlite_fts.py`), LanceDB (`lancedb_store.py`), shared models
- `db/` — database files (gitignored)

Requires Python 3.10+. Semantic search uses ONNX Runtime for fast inference (~265 MB exported model). Run `python3 scripts/export_onnx.py` once to export the model. Falls back to PyTorch/sentence-transformers if ONNX model is not exported.

---

## Русский

Полнотекстовый и семантический поиск по логам AI-агентов — Claude Code, Codex, Gemini, Aider.

### Что нового в v0.2

- **Холодный старт в 10 раз быстрее** — ONNX Runtime вместо PyTorch (0.8 сек vs 3 сек)
- **Фильтр шума** — 42% меньше шума при семантическом поиске (tool_use, системные сообщения отфильтрованы)
- **Исправление FTS5** — спецсимволы (дефисы, %, *, ^) больше не ломают поиск по ключевым словам
- **MCP-сервер** — поиск по сессиям напрямую из Claude Code

### Быстрый старт

```bash
pip install -r requirements.txt
python3 scripts/export_onnx.py   # один раз: экспортировать модель в ONNX (~265 МБ)
python3 cli.py index              # проиндексировать все логи
python3 cli.py search "запрос"    # поиск по ключевым словам
```

### Архитектура

```
cli.py / mcp_server.py
        |
        +-- Indexer (core/indexer.py)
        |       |
        |       +-- parsers/registry.py --> ClaudeParser  (~/.claude/projects/**/*.jsonl)
        |       |                       --> CodexParser   (~/.codex/sessions/rollout-*.jsonl)
        |       |                       --> GeminiParser  (заглушка)
        |       |                       --> AiderParser   (заглушка)
        |       |
        |       +-- SqliteFtsStore  (db/sessions.db)   Фаза 1: FTS5/BM25
        |       +-- LanceDBStore    (db/vectors/)       Фаза 2: эмбеддинги (опционально)
        |
        +-- SearchEngine (core/search.py)
                |
                +-- keyword  -> FTS5 OR-запрос
                +-- semantic -> косинусное сходство LanceDB
                +-- all      -> RRF-слияние (Reciprocal Rank Fusion)
                |
                +-- get_context() -> SessionFragment (совпадение + 2 сообщения до/после)
```

**Модель данных:** единица индексации — `LogEntry` — одно сообщение из сессии. Содержит: роль, текст, временную метку, псевдоним проекта, извлечённые пути к файлам и номера задач (issues).

### Использование CLI

#### Индексация

```bash
# Полная переиндексация (FTS + векторы если доступны)
python3 cli.py index

# Инкрементальная — только новые или изменённые файлы
python3 cli.py index --quick

# Перестроить только векторы из существующего FTS-индекса
python3 cli.py index --vectors-only

# Ограничить потребление RSS-памяти при индексации (по умолчанию: 1024 МБ)
python3 cli.py index --max-memory 2048
```

#### Поиск

```bash
# По ключевым словам (FTS5, режим по умолчанию)
python3 cli.py search "docker migration"

# Семантический поиск (требует векторный индекс)
python3 cli.py search -s "как мы решили утечку памяти"

# Оба режима через RRF
python3 cli.py search -a "authentication flow"

# Фильтр по проекту
python3 cli.py search "webhook" -p kfs

# Фильтр по агенту
python3 cli.py search "refactor" --agent codex

# Только последние 7 дней
python3 cli.py search "deploy" --days 7

# Фильтр по роли (user / assistant / tool_use / tool_result)
python3 cli.py search "issue" --role user

# Больше результатов
python3 cli.py search "запрос" --limit 20
```

#### Статистика

```bash
python3 cli.py stats
# Total entries: 142831
# By project: kfs: 89012  hq: 31045  jh: 14200 ...
# By agent:   claude: 138000  codex: 4831 ...
```

### MCP-сервер

Подключите session-memory как MCP-инструмент, чтобы Claude Code мог искать по прошлым сессиям напрямую.

Добавьте в `~/.claude/.mcp.json`:

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

Доступный инструмент: **`search_sessions`**

| Параметр | Тип | По умолчанию | Описание |
|----------|-----|--------------|----------|
| `query` | str | обязательный | Поисковый запрос |
| `project` | str | null | Фильтр: hq, kfs, jh, bb, aie... |
| `days` | int | 30 | Глубина поиска в днях |
| `limit` | int | 5 | Максимум результатов |

Возвращает компактные результаты: временная метка, проект, ID сессии, фрагмент текста (200 символов) и окружающий контекст. Системные сообщения и записи короче 50 символов отфильтровываются автоматически.

Если векторный индекс доступен — автоматически используется режим RRF. Иначе — поиск по ключевым словам.

### Конфигурация

| Переменная окружения | По умолчанию | Описание |
|---------------------|--------------|----------|
| `SM_DB_DIR` | `./db/` | Директория для SQLite и LanceDB |
| `SM_CLAUDE_LOGS` | `~/.claude/projects/` | Переопределить путь к логам Claude |

Псевдонимы проектов задаются в `config.py` → `PROJECT_MAP`. Добавьте туда своё репо, если оно не распознаётся автоматически.

### Добавить парсер

1. Создайте `parsers/youragent.py`, реализующий `BaseParser`:

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
        # Разберите путь, создайте LogEntry на каждое сообщение
        # Обязательные поля: agent_type, project, session_id, role, content, timestamp
        return entries
```

2. Зарегистрируйте в `parsers/registry.py` → `get_parsers()`:

```python
from parsers.youragent import YourParser

def get_parsers(...) -> list[BaseParser]:
    return [
        ClaudeParser(...),
        CodexParser(),
        YourParser(),   # добавьте сюда
        ...
    ]
```

3. Запустите `python3 cli.py index` — логи нового агента подхватятся автоматически.

### Разработка

```bash
# Установить зависимости
pip install -r requirements.txt

# Запустить тесты
pytest

# Запустить тесты подробно
pytest -v
```

Структура проекта:

- `core/` — индексер, поисковый движок, эмбеддер (без I/O)
- `parsers/` — один файл на тип агента
- `storage/` — SQLite FTS5 (`sqlite_fts.py`), LanceDB (`lancedb_store.py`), общие модели
- `db/` — файлы баз данных (в .gitignore)

Требуется Python 3.10+. Семантический поиск использует ONNX Runtime для быстрого инференса (~265 МБ экспортированная модель). Запустите `python3 scripts/export_onnx.py` один раз для экспорта. При отсутствии ONNX-модели используется PyTorch/sentence-transformers.
