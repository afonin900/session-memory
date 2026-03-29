# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.1] - 2026-03-29

### Fixed
- LanceDB `list_tables()` API compatibility with newer lancedb versions

## [0.2.0] - 2026-03-27

### Added
- ONNX Runtime embedder — 10x faster cold start vs PyTorch
- ONNX export script and config for `multilingual-e5-base` model
- Noise filter for vector indexing — skip `tool_use`, `system`, and XML blocks
- MCP server with full search integration
- SessionStart hook for automatic index loading
- Bilingual README (English + Russian)
- Full technical specification (`TECHNICAL.md`)

### Changed
- ONNX embedder facade with PyTorch fallback; removed torch from indexer
- Optimized vector indexing memory usage: 16GB → ~1GB target
- Optimized indexer: `batch_size=128`, 4 threads, vectors-only mode
- Pinned `fastmcp` dependency; applied code review fixes (noise filter, empty hint)
- Softened log messages and suppressed model load warnings

### Fixed
- Escape all FTS5 special characters (`%`, `*`, `^`, parentheses)
- Escape hyphens in FTS5 queries
- Delete orphaned vectors on re-index
- Escape `source_file` in LanceDB queries

## [0.1.0] - 2026-03-26

### Added
- Project scaffolding: config, models, directory structure
- SQLite FTS5 storage with keyword search and context windows
- Claude Code JSONL parser with tests
- Indexer with incremental support and parser registry
- Search engine with keyword mode and context windows
- CLI entry point: `index`, `search`, `stats` commands
- Embedder wrapper for `multilingual-e5-base`
- LanceDB vector storage with semantic search
- Wired LanceDB semantic search into indexer and CLI
- Codex JSONL parser
- Gemini and Aider stub parsers; all parsers registered in indexer
- Multi-agent support: Codex parser, agent filter, integration tests
- `CLAUDE.md` with usage, architecture, and extension guide

[Unreleased]: https://github.com/afonin900/session-memory/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/afonin900/session-memory/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/afonin900/session-memory/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/afonin900/session-memory/releases/tag/v0.1.0
