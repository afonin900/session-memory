# config.py
from pathlib import Path
import os

# Paths
PROJECT_ROOT = Path(__file__).parent
DB_DIR = Path(os.environ.get("SM_DB_DIR", PROJECT_ROOT / "db"))
SQLITE_PATH = DB_DIR / "sessions.db"
VECTORS_DIR = DB_DIR / "vectors"

# Claude Code logs
CLAUDE_LOGS_BASE = Path.home() / ".claude" / "projects"

# Codex logs
CODEX_LOGS_BASE = Path.home() / ".codex" / "sessions"

# Project name mapping (repo dir name -> short alias)
PROJECT_MAP = {
    "ai-corporation-kfs": "kfs",
    "job-hunter": "jh",
    "headquarters": "hq",
    "bricks-builder": "bb",
    "ai-engineer": "aie",
    "session-memory": "sm",
    "second-brain-bot": "sbb",
    "floristry": "fl",
    "paperclip": "pp",
}

# Indexing
TOOL_RESULT_MAX_LENGTH = 500
EMBEDDING_MODEL = "intfloat/multilingual-e5-base"
EMBEDDING_DIM = 768
ONNX_MODEL_DIR = PROJECT_ROOT / "models" / "multilingual-e5-base-onnx"
ONNX_MODEL_PATH = ONNX_MODEL_DIR / "model_quantized.onnx"
ONNX_TOKENIZER_NAME = "intfloat/multilingual-e5-base"

# Search defaults
DEFAULT_SEARCH_LIMIT = 10
CONTEXT_WINDOW = 2  # messages before/after match


def extract_project(cwd: str) -> str:
    """Extract project alias from cwd path."""
    if not cwd:
        return "unknown"
    parts = Path(cwd).parts
    for i, part in enumerate(parts):
        if part == "Github" and i + 1 < len(parts):
            repo_name = parts[i + 1]
            return PROJECT_MAP.get(repo_name, repo_name)
    return PROJECT_MAP.get(parts[-1], parts[-1])
