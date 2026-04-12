import pytest
from core.graph import extract_wiki_links


def test_extract_wiki_links():
    content = """
# Decision

See [[12-decision-channels]] and [[content-plan]] and [[marketing-strategy]].
"""
    links = extract_wiki_links(content)
    assert links == ["12-decision-channels", "content-plan", "marketing-strategy"]


def test_extract_wiki_links_empty():
    assert extract_wiki_links("No links here") == []


def test_extract_wiki_links_dedup():
    content = "See [[doc]] and again [[doc]]"
    links = extract_wiki_links(content)
    assert links == ["doc"]


def test_extract_preserves_order():
    content = "[[b]] then [[a]] then [[c]]"
    links = extract_wiki_links(content)
    assert links == ["b", "a", "c"]
