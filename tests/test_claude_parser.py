import json
import tempfile
from pathlib import Path
from parsers.claude import ClaudeParser

SAMPLE_LINES = [
    {
        "type": "progress",
        "data": {"type": "hook_progress", "hookEvent": "SessionStart"},
        "sessionId": "abc-123",
        "cwd": "/Users/test/Github/headquarters",
        "timestamp": "2026-03-25T10:00:00.000Z",
        "uuid": "u1"
    },
    {
        "type": "user",
        "message": {"role": "user", "content": "как деплоить docker на hetzner?"},
        "sessionId": "abc-123",
        "cwd": "/Users/test/Github/headquarters",
        "timestamp": "2026-03-25T10:00:01.000Z",
        "uuid": "u2"
    },
    {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "model": "claude-opus-4-6",
            "content": [
                {"type": "thinking", "thinking": "Let me think about this..."},
                {"type": "text", "text": "Для деплоя на Hetzner VPS нужно установить Docker."},
                {
                    "type": "tool_use",
                    "id": "toolu_01",
                    "name": "Read",
                    "input": {"file_path": "/home/user/.claude/refs/infra.md"}
                }
            ],
            "stop_reason": "tool_use"
        },
        "sessionId": "abc-123",
        "cwd": "/Users/test/Github/headquarters",
        "timestamp": "2026-03-25T10:00:05.000Z",
        "uuid": "u3"
    },
    {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_01",
                    "content": "# Infra reference\nServer: hetzner 159.69.216.152"
                }
            ]
        },
        "sessionId": "abc-123",
        "cwd": "/Users/test/Github/headquarters",
        "timestamp": "2026-03-25T10:00:06.000Z",
        "uuid": "u4",
        "toolUseResult": {"content": "# Infra reference..."}
    },
    {
        "type": "queue-operation",
        "operation": "enqueue",
        "sessionId": "abc-123",
        "timestamp": "2026-03-25T10:00:00.000Z"
    },
    {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "text", "text": "Check issue #84 and #2"}]},
        "sessionId": "abc-123",
        "cwd": "/Users/test/Github/ai-corporation-kfs",
        "timestamp": "2026-03-25T10:01:00.000Z",
        "uuid": "u5"
    }
]


def _write_sample_jsonl(tmp_dir: Path) -> Path:
    proj_dir = tmp_dir / "-Users-test-Github-headquarters"
    proj_dir.mkdir(parents=True)
    jsonl_path = proj_dir / "abc-123.jsonl"
    with open(jsonl_path, "w") as f:
        for line in SAMPLE_LINES:
            f.write(json.dumps(line) + "\n")
    return tmp_dir


def test_discover_sessions():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        _write_sample_jsonl(tmp_path)
        parser = ClaudeParser(logs_base=tmp_path)
        sessions = parser.discover_sessions()
        assert len(sessions) == 1
        assert sessions[0].name == "abc-123.jsonl"


def test_parse_filters_progress_and_queue():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        _write_sample_jsonl(tmp_path)
        parser = ClaudeParser(logs_base=tmp_path)
        sessions = parser.discover_sessions()
        entries = parser.parse_session(sessions[0])
        # progress and queue-operation should be filtered out
        assert not any("hook_progress" in e.content for e in entries)
        # Should have: user, assistant (text), tool_use, tool_result, user (with issues)
        assert len(entries) >= 4


def test_parse_extracts_text_skips_thinking():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        _write_sample_jsonl(tmp_path)
        parser = ClaudeParser(logs_base=tmp_path)
        entries = parser.parse_session(parser.discover_sessions()[0])
        assistant_texts = [e for e in entries if e.role == "assistant"]
        assert any("Для деплоя" in e.content for e in assistant_texts)
        assert not any("Let me think" in e.content for e in assistant_texts)


def test_parse_extracts_file_paths():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        _write_sample_jsonl(tmp_path)
        parser = ClaudeParser(logs_base=tmp_path)
        entries = parser.parse_session(parser.discover_sessions()[0])
        tool_entries = [e for e in entries if e.role == "tool_use"]
        assert len(tool_entries) >= 1
        assert "/home/user/.claude/refs/infra.md" in tool_entries[0].file_paths


def test_parse_extracts_issue_numbers():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        _write_sample_jsonl(tmp_path)
        parser = ClaudeParser(logs_base=tmp_path)
        entries = parser.parse_session(parser.discover_sessions()[0])
        issue_entries = [e for e in entries if e.issue_numbers]
        assert len(issue_entries) >= 1
        assert "84" in issue_entries[0].issue_numbers
        assert "2" in issue_entries[0].issue_numbers


def test_parse_maps_project_from_cwd():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        _write_sample_jsonl(tmp_path)
        parser = ClaudeParser(logs_base=tmp_path)
        entries = parser.parse_session(parser.discover_sessions()[0])
        hq_entries = [e for e in entries if e.project == "hq"]
        assert len(hq_entries) >= 1


def test_parse_truncates_tool_result():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        _write_sample_jsonl(tmp_path)
        parser = ClaudeParser(logs_base=tmp_path)
        entries = parser.parse_session(parser.discover_sessions()[0])
        tr_entries = [e for e in entries if e.role == "tool_result"]
        for e in tr_entries:
            assert len(e.content) <= 500
