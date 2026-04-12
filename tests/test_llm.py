import json
from unittest.mock import patch, MagicMock
from core.llm import call_llm, _get_api_key


def test_get_api_key_from_env():
    with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key-123"}):
        assert _get_api_key() == "test-key-123"


def test_call_llm_no_key():
    with patch("core.llm._get_api_key", return_value=None):
        result = call_llm("test prompt")
        assert result is None


def test_call_llm_success():
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({
        "choices": [{"message": {"content": "test response"}}]
    }).encode("utf-8")
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)

    with patch("core.llm._get_api_key", return_value="test-key"):
        with patch("core.llm.urlopen", return_value=mock_response):
            result = call_llm("test prompt")
            assert result == "test response"
