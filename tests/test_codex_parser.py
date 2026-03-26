import json
import tempfile
from pathlib import Path
from parsers.codex import CodexParser

SAMPLE_LINES = [
    {
        "timestamp": "2026-03-10T11:56:10.000Z",
        "type": "session_meta",
        "payload": {
            "id": "019cd763-d807-7930-bbf2-d888eb9dcdc4",
            "timestamp": "2026-03-10T11:56:10.000Z",
            "cwd": "/Users/test/Github/ai-corporation-kfs",
            "originator": "codex_sdk_ts",
            "cli_version": "0.98.0",
            "source": "exec",
            "model_provider": "openai",
        }
    },
    {
        "timestamp": "2026-03-10T11:56:11.000Z",
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "developer",
            "content": [{"type": "input_text", "text": "Fix the pipeline bug in transcription"}]
        }
    },
    {
        "timestamp": "2026-03-10T11:56:15.000Z",
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "I found the bug in pipeline.ts line 42."}]
        }
    },
    {
        "timestamp": "2026-03-10T11:56:16.000Z",
        "type": "event_msg",
        "payload": {"type": "agent_reasoning", "text": "Analyzing the codebase..."}
    },
    {
        "timestamp": "2026-03-10T11:56:20.000Z",
        "type": "response_item",
        "payload": {
            "type": "function_call",
            "name": "shell",
            "arguments": "{\"command\": \"cat src/pipeline.ts\"}"
        }
    },
    {
        "timestamp": "2026-03-10T11:56:21.000Z",
        "type": "response_item",
        "payload": {
            "type": "function_call_output",
            "output": "export function transcribe() { ... very long output ... }"
        }
    },
]


def _write_sample(tmp_dir: Path) -> Path:
    session_dir = tmp_dir / "2026" / "03" / "10"
    session_dir.mkdir(parents=True)
    path = session_dir / "rollout-2026-03-10T11-56-10-019cd763.jsonl"
    with open(path, "w") as f:
        for line in SAMPLE_LINES:
            f.write(json.dumps(line) + "\n")
    return tmp_dir


def test_discover_sessions():
    with tempfile.TemporaryDirectory() as tmp:
        base = _write_sample(Path(tmp))
        parser = CodexParser(logs_base=base)
        sessions = parser.discover_sessions()
        assert len(sessions) == 1


def test_parse_extracts_messages():
    with tempfile.TemporaryDirectory() as tmp:
        base = _write_sample(Path(tmp))
        parser = CodexParser(logs_base=base)
        entries = parser.parse_session(parser.discover_sessions()[0])
        roles = [e.role for e in entries]
        assert "user" in roles  # developer -> user
        assert "assistant" in roles


def test_parse_maps_developer_to_user():
    with tempfile.TemporaryDirectory() as tmp:
        base = _write_sample(Path(tmp))
        parser = CodexParser(logs_base=base)
        entries = parser.parse_session(parser.discover_sessions()[0])
        user_entries = [e for e in entries if e.role == "user"]
        assert any("pipeline bug" in e.content for e in user_entries)


def test_parse_extracts_project():
    with tempfile.TemporaryDirectory() as tmp:
        base = _write_sample(Path(tmp))
        parser = CodexParser(logs_base=base)
        entries = parser.parse_session(parser.discover_sessions()[0])
        assert any(e.project == "kfs" for e in entries)


def test_parse_handles_function_calls():
    with tempfile.TemporaryDirectory() as tmp:
        base = _write_sample(Path(tmp))
        parser = CodexParser(logs_base=base)
        entries = parser.parse_session(parser.discover_sessions()[0])
        tool_entries = [e for e in entries if e.role == "tool_use"]
        assert len(tool_entries) >= 1
        assert "shell" in tool_entries[0].content


def test_parse_truncates_function_output():
    with tempfile.TemporaryDirectory() as tmp:
        base = _write_sample(Path(tmp))
        parser = CodexParser(logs_base=base)
        entries = parser.parse_session(parser.discover_sessions()[0])
        tr_entries = [e for e in entries if e.role == "tool_result"]
        for e in tr_entries:
            assert len(e.content) <= 500


def test_agent_type_is_codex():
    with tempfile.TemporaryDirectory() as tmp:
        base = _write_sample(Path(tmp))
        parser = CodexParser(logs_base=base)
        entries = parser.parse_session(parser.discover_sessions()[0])
        assert all(e.agent_type == "codex" for e in entries)
