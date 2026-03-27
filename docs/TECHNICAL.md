# Session Memory — техническая документация

**Issue:** [HQ #84](https://github.com/afonin900/headquarters/issues/84)
**Версия спецификации:** 2026-03-26
**Стек:** Python 3.10+, SQLite FTS5, LanceDB, multilingual-e5-base

---

## 1. Обзор системы

### Цель

Session Memory — кросс-проектный инструмент полнотекстового и семантического поиска по логам AI-агентов. Логи Claude Code, Codex, Gemini и Aider хранятся в JSONL-файлах (~1.5 GB) без индекса. Инструмент решает три задачи:

1. Индексирует логи всех агентов из любого проекта экосистемы
2. Ищет по ключевым словам (FTS5, BM25) и по смыслу (semantic, LanceDB + e5-base)
3. Возвращает фрагмент диалога с контекстом, а не одну строку

### Архитектурная схема

```
cli.py (точка входа, argparse)
    |
    +-- cmd_index()
    |       |
    |       +-- Indexer (core/indexer.py)
    |               |
    |               +-- parsers/registry.py  --> ClaudeParser
    |               |                        --> CodexParser
    |               |                        --> GeminiParser (stub)
    |               |                        --> AiderParser  (stub)
    |               |
    |               +-- SqliteFtsStore (storage/sqlite_fts.py)
    |               +-- LanceDBStore   (storage/lancedb_store.py)  [optional]
    |
    +-- cmd_search()
            |
            +-- SearchEngine (core/search.py)
                    |
                    +-- SqliteFtsStore  (keyword, BM25)
                    +-- LanceDBStore    (semantic, cosine)  [optional]
                    +-- RRF merge       (mode=all)
                    |
                    +-- get_context() --> SessionFragment
```

### Стек

| Компонент | Технология | Версия |
|-----------|-----------|--------|
| Язык | Python | 3.10+ |
| Полнотекстовый поиск | SQLite FTS5 (встроен) | — |
| Векторное хранилище | LanceDB | >=0.15 |
| Эмбеддинги | multilingual-e5-base (ONNX) | sentence-transformers >=3.0 |
| Векторный формат | PyArrow | >=14.0 |
| Числа | NumPy | >=1.26 |
| Тесты | pytest | >=8.0 |

---

## 2. Модель данных

### LogEntry

Единица индексации — одно сообщение из сессии.

```python
@dataclass
class LogEntry:
    agent_type: str          # "claude" | "codex" | "gemini" | "aider"
    project: str             # alias из PROJECT_MAP: "kfs", "jh", "hq", "bb", "aie", "sm"
    session_id: str          # UUID сессии (из поля sessionId или имени файла)
    role: str                # "user" | "assistant" | "tool_use" | "tool_result" | "system"
    content: str             # текст сообщения
    timestamp: datetime      # UTC datetime
    file_paths: list[str]    # пути из tool_use (Read/Write/Edit/Glob/Grep)
    issue_numbers: list[str] # regex #\d+ из content
    source_file: str         # абсолютный путь к JSONL-файлу
```

### SearchResult

Результат поиска — LogEntry с добавленным score.

```python
@dataclass
class SearchResult:
    id: int                  # rowid из sessions_log (SQLite)
    agent_type: str
    project: str
    session_id: str
    role: str
    content: str
    timestamp: datetime
    file_paths: list[str]
    issue_numbers: list[str]
    score: float             # BM25 rank (FTS5) или cosine distance (LanceDB)
```

### SessionFragment

Контекстное окно вокруг найденного сообщения.

```python
@dataclass
class SessionFragment:
    match: SearchResult          # найденная запись
    before: list[SearchResult]   # до 2 сообщений до match из той же сессии
    after: list[SearchResult]    # до 2 сообщений после match из той же сессии
    session_id: str
    project: str
```

### PROJECT_MAP

Маппинг имени репозитория в короткий alias. Используется в `config.py` и `extract_project()`.

```python
PROJECT_MAP = {
    "ai-corporation-kfs": "kfs",
    "job-hunter":         "jh",
    "headquarters":       "hq",
    "bricks-builder":     "bb",
    "ai-engineer":        "aie",
    "session-memory":     "sm",
    "second-brain-bot":   "sbb",
    "floristry":          "fl",
    "paperclip":          "pp",
}
```

Функция `extract_project(cwd: str) -> str` ищет сегмент `Github` в пути `cwd` и возвращает alias следующего сегмента. Если alias не найден — возвращает имя директории или `"unknown"`.

### Фильтрация событий при индексации

| Тип события / поле | Действие | Причина |
|--------------------|----------|---------|
| `user` message (строка или text-блок) | Индексировать полностью | Основной ввод пользователя |
| `assistant` text-блок | Индексировать полностью | Ответ агента |
| `assistant` tool_use | Индексировать: `tool_name param=val` (обрезка до 100 символов) | Краткое действие, не полный input |
| `assistant` thinking-блок | Пропустить | Огромный объём, приватные рассуждения |
| `tool_result` (в user-сообщении) | Индексировать, обрезать до 500 символов | Результаты инструментов слишком велики |
| `progress` event | Пропустить | Служебный прогресс |
| `queue-operation` event | Пропустить | Внутренняя очередь Claude Code |
| `isMeta: true` (user event) | Пропустить | Метаданные системы, не диалог |
| `system` event | Индексировать как `[subtype]` | Маркер старта/стопа сессии |

---

## 3. Хранилища

### SQLite FTS5

**Файл:** `storage/sqlite_fts.py`
**Путь к базе:** `db/sessions.db` (или `$SM_DB_DIR/sessions.db`)

#### Полная SQL-схема

```sql
-- Основная таблица логов
CREATE TABLE IF NOT EXISTS sessions_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_type  TEXT    NOT NULL,
    project     TEXT    NOT NULL,
    session_id  TEXT    NOT NULL,
    role        TEXT    NOT NULL,
    content     TEXT    NOT NULL,
    timestamp   DATETIME NOT NULL,
    file_paths   TEXT    DEFAULT '[]',    -- JSON array строк
    issue_numbers TEXT   DEFAULT '[]',    -- JSON array строк ("#123")
    source_file TEXT    NOT NULL
);

-- FTS5 виртуальная таблица (content-таблица поверх sessions_log)
CREATE VIRTUAL TABLE IF NOT EXISTS sessions_fts USING fts5(
    content, file_paths, project,
    content=sessions_log, content_rowid=id
);

-- Трекинг проиндексированных файлов
CREATE TABLE IF NOT EXISTS indexed_files (
    source_file TEXT PRIMARY KEY,
    mtime       REAL    NOT NULL,         -- float mtime из os.stat()
    entry_count INTEGER DEFAULT 0,
    indexed_at  DATETIME DEFAULT (datetime('now'))
);

-- Триггер: авто-вставка в FTS5 при INSERT
CREATE TRIGGER IF NOT EXISTS sessions_log_ai AFTER INSERT ON sessions_log BEGIN
    INSERT INTO sessions_fts(rowid, content, file_paths, project)
    VALUES (new.id, new.content, new.file_paths, new.project);
END;

-- Триггер: авто-удаление из FTS5 при DELETE
CREATE TRIGGER IF NOT EXISTS sessions_log_ad AFTER DELETE ON sessions_log BEGIN
    INSERT INTO sessions_fts(sessions_fts, rowid, content, file_paths, project)
    VALUES ('delete', old.id, old.content, old.file_paths, old.project);
END;
```

#### Таблица indexed_files — инкрементальная индексация

`indexed_files` хранит `source_file → mtime` для каждого JSONL-файла. Алгоритм проверки:

```python
def is_indexed(source_file: str, mtime: float) -> bool:
    row = conn.execute(
        "SELECT mtime FROM indexed_files WHERE source_file = ?", (source_file,)
    ).fetchone()
    return row is not None and row["mtime"] == mtime
```

Пустые файлы (0 записей) тоже маркируются как проиндексированные — чтобы не перепроверять их при каждом `--quick`.

#### Алгоритм поиска (BM25)

FTS5 использует BM25 внутри движка SQLite. Поле `rank` — отрицательное число (чем ближе к 0, тем релевантнее). Поиск по трём полям: `content`, `file_paths`, `project`.

```sql
SELECT s.*, sessions_fts.rank AS score
FROM sessions_fts
JOIN sessions_log s ON s.id = sessions_fts.rowid
WHERE sessions_fts MATCH ?        -- FTS5 query
  AND s.project = ?               -- опционально
  AND s.agent_type = ?            -- опционально
  AND s.timestamp > ?             -- опционально (days filter)
  AND s.role = ?                  -- опционально
ORDER BY sessions_fts.rank        -- BM25, ascending (ближе к 0 = лучше)
LIMIT ?;
```

**Pragma настройки при инициализации:**

```python
conn.execute("PRAGMA journal_mode=WAL")    # конкурентные читатели
conn.execute("PRAGMA busy_timeout=5000")   # 5 сек ожидание при lock
```

---

### LanceDB

**Файл:** `storage/lancedb_store.py`
**Путь:** `db/vectors/` (директория LanceDB)
**Таблица:** `sessions_vectors`

#### PyArrow схема таблицы

```python
import pyarrow as pa
from config import EMBEDDING_DIM  # 768

_SCHEMA = pa.schema([
    pa.field("id",          pa.int64()),                         # FK -> sessions_log.id
    pa.field("text",        pa.string()),                        # content для отображения
    pa.field("vector",      pa.list_(pa.float32(), EMBEDDING_DIM)),  # float32[768]
    pa.field("agent_type",  pa.string()),
    pa.field("project",     pa.string()),
    pa.field("session_id",  pa.string()),
    pa.field("role",        pa.string()),
    pa.field("timestamp",   pa.string()),                        # ISO 8601
    pa.field("source_file", pa.string()),
])
```

| Поле | Тип PyArrow | Назначение |
|------|------------|------------|
| `id` | int64 | FK к `sessions_log.id`, связь для get_context() |
| `text` | string | content для вывода в результатах |
| `vector` | float32[768] | эмбеддинг, ANN-поиск |
| `agent_type` | string | фильтрация |
| `project` | string | фильтрация |
| `session_id` | string | группировка |
| `role` | string | фильтрация |
| `timestamp` | string | ISO 8601, фильтрация по дате |
| `source_file` | string | удаление при реиндексации |

#### Размерность и модель

- Размерность вектора: **768** (`EMBEDDING_DIM` в `config.py`)
- Модель: `intfloat/multilingual-e5-base`
- Нормализация: L2-нормализация при encode (`normalize_embeddings=True`)
- Тип: `float32` (после `.astype(np.float32)`)

#### Prefixes по спецификации e5

Модель `multilingual-e5-base` требует разных префиксов для запросов и документов:

```python
# Запрос пользователя:
f"query: {text}"

# Текст документа при индексации:
f"passage: {text}"
```

#### Lazy loading модели

Модель (~400 MB) загружается только при первом вызове семантического поиска или при индексации с LanceDB. FTS5-only поиск не затрагивает модель.

```python
class Embedder:
    _model = None  # class-level singleton

    def _load(self):
        if Embedder._model is None:
            from sentence_transformers import SentenceTransformer
            Embedder._model = SentenceTransformer(EMBEDDING_MODEL)
```

---

## 4. Парсеры

### Архитектура парсеров

**Файл:** `parsers/base.py`

```python
class BaseParser(ABC):
    agent_type: str = ""   # "claude" | "codex" | "gemini" | "aider"

    @abstractmethod
    def discover_sessions(self) -> list[Path]:
        """Найти все JSONL-файлы этого агента."""

    @abstractmethod
    def parse_session(self, path: Path) -> list[LogEntry]:
        """Распарсить один файл в список LogEntry."""
```

### Registry

**Файл:** `parsers/registry.py`

```python
def get_parsers(claude_logs_base: Path | None = None) -> list[BaseParser]:
    return [
        ClaudeParser(logs_base=claude_logs_base),
        CodexParser(),
        GeminiParser(),
        AiderParser(),
    ]

def discover_all(parsers=None) -> Iterator[tuple[BaseParser, Path]]:
    for parser in (parsers or get_parsers()):
        for path in parser.discover_sessions():
            yield parser, path
```

`get_parsers()` — фабрика, принимает необязательный `claude_logs_base` для переопределения пути через `SM_CLAUDE_LOGS`. Все остальные парсеры используют константы из `config.py`.

---

### Claude Code Parser

**Файл:** `parsers/claude.py`
**agent_type:** `"claude"`

#### Путь логов

```
~/.claude/projects/**/*.jsonl
```

Структура директорий Claude Code: каждый проект кодируется в имя директории через замену `/` на `-`. Например:
```
~/.claude/projects/-Users-afonin900-Github-headquarters/
    <session_uuid>.jsonl
    <session_uuid>.jsonl
```

`discover_sessions()` использует `rglob("*.jsonl")` — рекурсивный поиск по всем подпапкам.

#### Формат JSONL

Каждая строка — JSON-объект с обязательными полями:

```json
{
  "type": "user" | "assistant" | "system" | "progress" | "queue-operation" | "last-prompt",
  "timestamp": "2026-03-25T14:32:00.000Z",
  "sessionId": "abc123...",
  "cwd": "/Users/afonin900/Github/headquarters",
  "isMeta": false,
  "message": { ... }
}
```

#### Типы событий и обработка

| Тип `type` | Обработка |
|-----------|----------|
| `user` (не isMeta) | Парсится `message.content` — строка или массив блоков |
| `assistant` | Парсится `message.content[]` — массив блоков |
| `system` | Создаётся запись `[subtype]` |
| `progress` | Пропускается |
| `queue-operation` | Пропускается |
| `last-prompt` | Пропускается |
| `user` (isMeta: true) | Пропускается |

#### Извлечение из assistant-сообщений

`message.content[]` — массив блоков. Обрабатываются три типа:

- **`type: "thinking"`** — пропускается полностью
- **`type: "text"`** — объединяется в одну `assistant` запись
- **`type: "tool_use"`** — создаётся отдельная `tool_use` запись с кратким summary:

```python
summary = f"{tool_name} {param}={value[:100]}"
# Пример: "Read file_path=/Users/afonin900/Github/hq/config.py"
```

Параметры для summary: `file_path`, `path`, `pattern`, `query`, `command`, `skill`.

#### Извлечение file_paths из tool_use

Только для инструментов `_FILE_TOOLS = {"Read", "Write", "Edit", "Glob", "Grep"}`.
Параметры `_FILE_PARAMS = {"file_path", "path", "pattern"}`.

#### Извлечение issue_numbers

Regex `#(\d+)` применяется ко всему content. Дубликаты дедуплицируются через `set()`.

#### session_id

Берётся из поля `sessionId` в каждой строке JSONL. Если поле отсутствует — используется `path.stem` (имя файла без расширения, обычно UUID).

---

### Codex Parser

**Файл:** `parsers/codex.py`
**agent_type:** `"codex"`

#### Путь логов

```
~/.codex/sessions/**/rollout-*.jsonl
```

`discover_sessions()` использует `rglob("rollout-*.jsonl")`.

#### Формат JSONL

```json
{
  "type": "session_meta" | "response_item" | "event_msg" | "turn_context",
  "timestamp": "...",
  "payload": { ... }
}
```

#### Типы событий Codex

| Тип `type` | Обработка |
|-----------|----------|
| `session_meta` | Извлекается `session_id` и `cwd` для всего файла |
| `response_item` | Основные данные (см. ниже) |
| `event_msg` | Пропускается (не полезно для поиска) |
| `turn_context` | Пропускается |

#### response_item.payload.type

| `payload.type` | Обработка |
|---------------|----------|
| `message` | Создаётся LogEntry с ролью через `_ROLE_MAP` |
| `function_call` | Создаётся `tool_use` запись: `fn_name + args[:100]` |
| `function_call_output` | Создаётся `tool_result` запись, обрезка до 500 символов |

#### Маппинг ролей

```python
_ROLE_MAP = {
    "developer": "user",   # Codex использует "developer" вместо "user"
    "user":      "user",
    "assistant": "assistant",
    "system":    "system",
}
```

#### message.content[]

Для `response_item.type=message` ищутся ключи `text`, `input_text`, `output_text` в каждом блоке контента.

---

### Gemini / Aider

**Файлы:** `parsers/gemini.py`, `parsers/aider.py`

Заглушки, готовые к реализации:

```python
class GeminiParser(BaseParser):
    agent_type = "gemini"

    def discover_sessions(self) -> list[Path]:
        return []   # будет: ~/.gemini/... или tmux output

    def parse_session(self, path: Path) -> list[LogEntry]:
        return []
```

При добавлении парсера — реализовать оба метода и добавить в `parsers/registry.py`.

---

## 5. Индексация

**Файл:** `core/indexer.py`

### Полная индексация (`index` без флагов)

```
1. discover_all()
   -> для каждого парсера: parser.discover_sessions()
   -> итерирует (parser, path) по всем найденным файлам

2. Для каждого файла:
   a. delete_by_source(path) — удалить старые записи (триггер чистит FTS5)
   b. parser.parse_session(path) -> list[LogEntry]
   c. Если entries не пустой:
      - store.insert_entries(entries) -> list[int] (ids)
      - vector_store.insert_entries(entries, ids)  [если LanceDB доступен]
   d. store.mark_indexed(path, mtime, len(entries))  -- даже если пустой файл

3. Возврат: {"files_indexed": N, "entries_added": M}
```

### Инкрементальная индексация (`index --quick`)

```
1. discover_all()

2. Для каждого файла:
   a. mtime = path.stat().st_mtime
   b. store.is_indexed(path, mtime)?
      -> YES: files_skipped += 1, continue
      -> NO:  перейти к шагу c

   c. delete_by_source(path)  -- удалить устаревшие записи
   d. parse_session(path)
   e. insert (SQLite + LanceDB)
   f. mark_indexed(path, mtime, count)

3. Возврат: {"files_indexed": N, "files_skipped": M, "entries_added": K}
```

Предназначена для запуска в SessionStart hook. На типичном объёме (1-3 новых файла) выполняется менее 2 секунд.

### Опциональность LanceDB

`Indexer` и `SearchEngine` принимают `vector_store=None`. Если LanceDB не установлен или недоступен, `cli.py` перехватывает `ImportError` и передаёт `None`:

```python
def _get_vector_store():
    try:
        from storage.lancedb_store import LanceDBStore
        from core.embedder import Embedder
        ...
        return vstore
    except ImportError:
        return None
```

Фаза 1 (FTS5) работает полностью без LanceDB и без загрузки модели.

---

## 6. Поиск

**Файл:** `core/search.py`

### Режимы поиска

`SearchEngine.search()` принимает `mode: str`:

| Режим | CLI флаг | Алгоритм |
|-------|---------|---------|
| `"keyword"` | (по умолчанию) | SQLite FTS5, BM25 |
| `"semantic"` | `-s` / `--semantic` | LanceDB ANN, cosine similarity |
| `"all"` | `-a` / `--all` | FTS5 + LanceDB, объединение через RRF |

### Keyword Search (FTS5)

```sql
SELECT s.*, sessions_fts.rank AS score
FROM sessions_fts
JOIN sessions_log s ON s.id = sessions_fts.rowid
WHERE sessions_fts MATCH ?
  [AND s.project = ?]
  [AND s.agent_type = ?]
  [AND s.timestamp > ?]
  [AND s.role = ?]
ORDER BY sessions_fts.rank
LIMIT 20;
```

BM25 score хранится в `sessions_fts.rank`. Значение отрицательное — сортировка по возрастанию (чем ближе к 0, тем выше релевантность).

### Semantic Search (LanceDB)

```python
query_vec = embedder.embed_query(query)  # "query: {text}"

table.search(query_vec.tolist())
     .where("project = 'kfs'")           # опциональные фильтры
     .limit(20)
     .to_pandas()
```

Возвращает `_distance` (cosine distance). Меньше = ближе к запросу.

### Merged Search — Reciprocal Rank Fusion

```
1. FTS5 search -> keyword_results (up to 20)
2. LanceDB search -> semantic_results (up to 20)

3. RRF scoring (k=60):
   for rank, result in enumerate(keyword_results):
       scores[result.id] += 1.0 / (60 + rank + 1)
   for rank, result in enumerate(semantic_results):
       scores[result.id] += 1.0 / (60 + rank + 1)

4. Дедупликация: all_results = {id: result} из обоих списков
5. Сортировка по RRF score (desc)
6. Возврат top-N
```

RRF объединяет два разных ранжирования без нормализации их score. Параметр `k=60` — стандартное значение, балансирует влияние высоких и низких позиций.

### Контекстное окно

После получения списка результатов для каждого `SearchResult` строится `SessionFragment`:

```python
# before: N сообщений ДО match в той же сессии
before_rows = conn.execute(
    "SELECT * FROM sessions_log WHERE session_id = ? AND id < ? ORDER BY id DESC LIMIT ?",
    (session_id, entry_id, CONTEXT_WINDOW)  # CONTEXT_WINDOW = 2
).fetchall()

# after: N сообщений ПОСЛЕ match
after_rows = conn.execute(
    "SELECT * FROM sessions_log WHERE session_id = ? AND id > ? ORDER BY id ASC LIMIT ?",
    (session_id, entry_id, CONTEXT_WINDOW)
).fetchall()
```

`before` возвращается в хронологическом порядке (reversed после DESC-выборки).

---

## 7. CLI

**Файл:** `cli.py`

### Команды

```bash
# Полная индексация всех логов
python3 cli.py index

# Инкрементальная индексация (только новые/изменённые файлы)
python3 cli.py index --quick

# Перестроить векторный индекс из существующих FTS-записей (без повторного парсинга)
python3 cli.py index --vectors-only

# Ограничить потребление RSS-памяти при векторной индексации (по умолчанию: 1024 МБ)
python3 cli.py index --max-memory 2048

# Keyword search (FTS5, по умолчанию)
python3 cli.py search "docker deploy"

# Semantic search (LanceDB + e5-base)
python3 cli.py search -s "когда чинили потерю данных"

# Merged search (FTS5 + LanceDB через RRF)
python3 cli.py search -a "docker deploy"

# Фильтры
python3 cli.py search "pdf.py" -p kfs              # по проекту
python3 cli.py search "pdf.py" --agent claude       # по агенту
python3 cli.py search "pdf.py" --days 7             # за последние 7 дней
python3 cli.py search "pdf.py" --role user          # только user-сообщения
python3 cli.py search "pdf.py" --limit 5            # ограничение результатов

# Статистика индекса
python3 cli.py stats
```

### Параметры команды index

| Параметр | Тип | По умолчанию | Описание |
|---------|-----|-------------|---------|
| `--quick` | flag | False | Инкрементальная индексация (только новые/изменённые файлы) |
| `--vectors-only` | flag | False | Пропустить FTS-парсинг, только перестроить векторный индекс |
| `--max-memory` | int (MB) | 1024 | Потолок RSS-памяти в МБ — форсирует gc и переподключение LanceDB при превышении |

### Параметры команды search

| Параметр | Тип | По умолчанию | Описание |
|---------|-----|-------------|---------|
| `query` | positional | — | Текст запроса |
| `-s` / `--semantic` | flag | False | Семантический поиск |
| `-a` / `--all` | flag | False | FTS5 + LanceDB merged |
| `-p` / `--project` | str | None | Фильтр по проекту (hq, kfs, jh...) |
| `--agent` | str | None | Фильтр по агенту (claude, codex...) |
| `--days` | int | None | Только последние N дней |
| `--role` | str | None | Фильтр по роли (user, assistant...) |
| `--limit` | int | 10 | Максимум результатов |

### Переменные окружения

| Переменная | По умолчанию | Описание |
|-----------|-------------|---------|
| `SM_DB_DIR` | `./db/` (относительно `cli.py`) | Директория базы данных |
| `SM_CLAUDE_LOGS` | `~/.claude/projects/` | Путь к логам Claude Code |

### Формат вывода

```
── [hq] 2026-03-25 14:32 (claude, session abc123de) ──
  [user] как деплоить docker на hetzner?
> [assistant] Для деплоя на Hetzner VPS нужно...
  [tool_use] Read file_path=~/.claude/refs/infra.md
──────────────────────────────────────────────────────
```

- Заголовок: `[project] дата время (agent_type, session XXXXXXXX)`
- `>` маркер: matched строка
- Отступ `  `: контекстные строки (before/after)
- Контент обрезается: match до 200 символов, before/after до 120 символов
- Перевод строк заменяется пробелами в preview

### Команда stats

Выводит:
- Total entries — всего записей в SQLite
- By project — количество записей по проектам (sorted desc)
- By agent — количество записей по агентам (sorted desc)

---

## 8. Интеграция с экосистемой

### SessionStart hook — автоиндексация

В хуке `SessionStart` любого проекта или глобально:

```bash
python3 ~/Github/session-memory/cli.py index --quick 2>/dev/null &
```

Запускается в фоне (`&`), не блокирует старт сессии. Ошибки подавляются (`2>/dev/null`). На типичном объёме (1-3 новых JSONL-файла) завершается за 1-2 секунды.

### Вызов из агентов

Любой AI-агент из любого проекта экосистемы:

```bash
# Найти решения из прошлых сессий
python3 ~/Github/session-memory/cli.py search "query"

# Найти только в конкретном проекте
python3 ~/Github/session-memory/cli.py search "query" -p kfs

# Семантический поиск (нужен LanceDB + модель)
python3 ~/Github/session-memory/cli.py search -s "смысловой запрос"
```

Инструмент работает из любой рабочей директории — путь к `cli.py` абсолютный.

### MCP Server (реализован)

`mcp_server.py` — тонкая обёртка над `core/`, работает параллельно с CLI. Один и тот же `core/` обслуживает оба интерфейса.

**Стек:** FastMCP 3.1, stdio transport

**Инструмент `search_sessions`:**

```python
@mcp.tool
def search_sessions(
    query: str,
    project: str | None = None,
    days: int = 30,
    limit: int = 5,
) -> list[dict]:
```

| Параметр | Тип | По умолчанию | Описание |
|---------|-----|-------------|---------|
| `query` | str | — | Ключевое слово или семантический запрос |
| `project` | str | None | Фильтр по проекту (hq, kfs, jh, bb, aie...) |
| `days` | int | 30 | Глубина поиска в днях |
| `limit` | int | 5 | Максимум результатов |

**Lazy init:** движок (`SearchEngine`) создаётся при первом вызове. Модель e5-base (~400 MB) загружается только если LanceDB доступен и есть векторный индекс.

**Fallback:** если LanceDB доступен — используется RRF (`mode="all"`), иначе keyword (`mode="keyword"`). При ошибке RRF (устаревшие vector ID) — автоматический откат на keyword.

**Noise filtering:** записи с `role == "system"` и `len(content) < 50` символов (служебные метки, "Tool loaded.", ".") отфильтровываются из результатов.

**Формат вывода** — компактный JSON:

```json
[
  {
    "ts": "2026-03-25 14:32",
    "project": "hq",
    "session": "abc123de",
    "snippet": "Для деплоя на Hetzner VPS нужно...",
    "context": [
      "[user] как деплоить docker на hetzner?",
      "[tool_use] Read file_path=~/.claude/refs/infra.md"
    ]
  }
]
```

Если результатов нет — возвращается `[{"info": "No results for '...' in last N days"}]`.

---

## 9. Расширение

### Добавление нового парсера

1. Создать `parsers/newagent.py`, унаследовав `BaseParser`:

```python
from parsers.base import BaseParser
from storage.models import LogEntry
from pathlib import Path

class NewAgentParser(BaseParser):
    agent_type = "newagent"

    def discover_sessions(self) -> list[Path]:
        logs_base = Path.home() / ".newagent" / "sessions"
        if not logs_base.exists():
            return []
        return sorted(logs_base.rglob("*.jsonl"))

    def parse_session(self, path: Path) -> list[LogEntry]:
        entries = []
        # ... парсинг специфичного формата ...
        return entries
```

2. Зарегистрировать в `parsers/registry.py`:

```python
from parsers.newagent import NewAgentParser

def get_parsers(claude_logs_base=None) -> list[BaseParser]:
    return [
        ClaudeParser(logs_base=claude_logs_base),
        CodexParser(),
        GeminiParser(),
        AiderParser(),
        NewAgentParser(),   # добавить сюда
    ]
```

3. Написать тест в `tests/test_newagent_parser.py` по образцу `tests/test_claude_parser.py`.

### Добавление нового фильтра в поиск

1. Добавить параметр в `SqliteFtsStore.search()` в `storage/sqlite_fts.py`
2. Добавить условие `conditions.append(...)` и `params.append(...)`
3. Повторить для `LanceDBStore.search()` в `storage/lancedb_store.py` (SQL-фильтр для `.where()`)
4. Добавить параметр в `SearchEngine.search()` в `core/search.py` и пробросить в оба хранилища
5. Добавить аргумент в `argparse` в `cli.py` и передать в `engine.search()`

### Фасад MCP

`mcp_server.py` реализован как тонкая обёртка над `core/` без изменений в `core/`, `storage/`, `parsers/`:

```
mcp_server.py
    +-- _get_store()         — SqliteFtsStore (с SM_DB_DIR override)
    +-- _get_vector_store()  — LanceDBStore + Embedder (опционально)
    +-- _get_engine()        — lazy-init SearchEngine singleton
    +-- search_sessions()    — единственный MCP tool
```

Конфигурация через переменные окружения (те же что у CLI): `SM_DB_DIR`, `SM_CLAUDE_LOGS`.

---

## 10. Зависимости и требования

### Python

Требуется Python **3.10+** (использует `X | Y` union types и `match/case`-совместимый синтаксис). Рекомендуется Python 3.12+.

### Зависимости

| Пакет | Версия | Назначение |
|-------|--------|-----------|
| `lancedb` | >=0.15 | Векторное хранилище |
| `pyarrow` | >=14.0 | Схема таблиц LanceDB |
| `sentence-transformers` | >=3.0 | Загрузка и inference e5-base |
| `numpy` | >=1.26 | Векторные операции, float32 cast |
| `pytest` | >=8.0 | Тесты |
| `sqlite3` | встроен | FTS5 (доступен в Python на macOS) |

Установка:

```bash
pip install lancedb pyarrow sentence-transformers numpy
```

### Модель multilingual-e5-base

- Размер: ~400 MB (скачивается при первом семантическом поиске)
- Путь кэша: `~/.cache/huggingface/hub/` (стандартный HuggingFace кэш)
- Загрузка только при необходимости — lazy singleton в `Embedder`

### Размер базы данных

Ориентировочные объёмы при индексации типичной экосистемы:

| Хранилище | Объём |
|-----------|-------|
| `sessions.db` (SQLite FTS5) при ~200K записей | ~100-150 MB |
| `db/vectors/` (LanceDB float32[768]) при ~200K записей | ~600-700 MB |

SQLite FTS5 без LanceDB — минимальный режим, достаточный для большинства задач поиска по ключевым словам.

---

## Структура файлов

```
session-memory/
  cli.py                    # CLI entry point (argparse)
  mcp_server.py             # MCP entry point (FastMCP 3.1, stdio)
  config.py                 # пути, константы, PROJECT_MAP
  requirements.txt
  CLAUDE.md
  core/
    indexer.py              # Indexer: discover -> parse -> store
    search.py               # SearchEngine: keyword | semantic | merged
    embedder.py             # Embedder: lazy e5-base singleton
  parsers/
    base.py                 # BaseParser ABC
    registry.py             # get_parsers() factory, discover_all()
    claude.py               # Claude Code JSONL parser (полная реализация)
    codex.py                # Codex JSONL parser (полная реализация)
    gemini.py               # GeminiParser stub
    aider.py                # AiderParser stub
  storage/
    models.py               # LogEntry, SearchResult, SessionFragment
    sqlite_fts.py           # SqliteFtsStore: FTS5, indexed_files, get_context
    lancedb_store.py        # LanceDBStore: ANN search, insert, delete
  tests/
    test_claude_parser.py
    test_codex_parser.py
    test_sqlite_fts.py
    test_lancedb_store.py
    test_search.py
    test_embedder.py
    test_indexer.py
    test_cli.py
    test_semantic_integration.py
    test_multiagent.py
  db/                       # данные (gitignored)
    sessions.db             # SQLite база
    vectors/                # LanceDB директория
  docs/
    TECHNICAL.md            # этот файл
```
