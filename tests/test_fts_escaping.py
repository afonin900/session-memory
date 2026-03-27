import pytest
from storage.sqlite_fts import _escape_fts5_query

def test_hyphen_escaped():
    assert _escape_fts5_query("kfs-app") == '"kfs-app"'

def test_multiple_hyphens():
    assert _escape_fts5_query("ai-corporation-kfs") == '"ai-corporation-kfs"'

def test_percent_escaped():
    assert _escape_fts5_query("100%") == '"100%"'

def test_asterisk_escaped():
    assert _escape_fts5_query("test*") == '"test*"'

def test_parentheses_escaped():
    assert _escape_fts5_query("(test)") == '"(test)"'

def test_caret_escaped():
    assert _escape_fts5_query("^test") == '"^test"'

def test_operators_preserved():
    assert _escape_fts5_query("foo AND bar") == "foo AND bar"
    assert _escape_fts5_query("foo OR bar") == "foo OR bar"
    assert _escape_fts5_query("NOT foo") == "NOT foo"

def test_mixed_operators_and_special():
    assert _escape_fts5_query("kfs-app AND deploy") == '"kfs-app" AND deploy'

def test_already_quoted_unchanged():
    assert _escape_fts5_query('"kfs-app"') == '"kfs-app"'

def test_plain_words_unchanged():
    assert _escape_fts5_query("docker deploy test") == "docker deploy test"

def test_empty_query():
    assert _escape_fts5_query("") == ""
