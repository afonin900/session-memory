#!/bin/bash
echo "WARNING: Full reindex — use only for initial setup or migration"
echo "For normal operation, sessions are indexed incrementally on session start"

# Полная переиндексация с векторами
# Сбрасывает indexed_files чтобы пересоздать LanceDB индекс
# Запускать когда векторный индекс пуст или устарел

DB="/Users/afonin900/Github/session-memory/db/sessions.db"
CLI="/Users/afonin900/Github/session-memory/cli.py"
LOG="/Users/afonin900/Github/session-memory/db/reindex.log"

echo "$(date): Starting full vector reindex" >> "$LOG"

# Сбросить indexed_files чтобы index пересоздал всё
sqlite3 "$DB" "DELETE FROM indexed_files;"

# Запустить полную индексацию (с LanceDB)
/opt/homebrew/bin/python3 "$CLI" index >> "$LOG" 2>&1

echo "$(date): Reindex complete" >> "$LOG"
