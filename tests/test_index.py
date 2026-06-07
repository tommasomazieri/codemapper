"""Tests for codemapper.index doc store, caching, and incremental refresh."""
import os
from pathlib import Path

import pytest

from codemapper.index import CodeIndex


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "mod.py").write_text('"""Mod header.\n\nSecond line."""\nX = 1\n', encoding="utf-8")
    (tmp_path / "conf.json").write_text('{"b": 1, "a": 2}', encoding="utf-8")
    (tmp_path / "readme.md").write_text("# Title\n## Sec\n", encoding="utf-8")
    return tmp_path


def test_build_populates_docs(repo: Path):
    index = CodeIndex(repo)
    index.build()
    assert index.all_docs() == ["conf.json", "readme.md"]
    assert index.get_doc("conf.json").top_keys == ["a", "b"]
    assert index.get_doc("readme.md").headings == ["# Title", "## Sec"]


def test_module_doc_full_and_span(repo: Path):
    index = CodeIndex(repo)
    index.build()
    pf = index.get_file("mod.py")
    assert pf.module_doc == "Mod header."
    assert pf.module_doc_full == "Mod header.\n\nSecond line."
    assert pf.doc_start_line == 1
    assert pf.doc_end_line == 3


def test_cache_round_trips_docs(repo: Path):
    CodeIndex(repo).build()  # writes cache
    fresh = CodeIndex(repo)
    assert fresh.refresh() is None  # loads from cache, no rebuild needed
    assert fresh.all_docs() == ["conf.json", "readme.md"]
    assert fresh.get_doc("conf.json").top_keys == ["a", "b"]
    # ParsedFile new fields survive the round-trip
    assert fresh.get_file("mod.py").module_doc_full == "Mod header.\n\nSecond line."


def test_refresh_picks_up_doc_change(repo: Path):
    index = CodeIndex(repo)
    index.build()
    conf = repo / "conf.json"
    conf.write_text('{"c": 9}', encoding="utf-8")
    os.utime(conf, (1, 1))  # force a distinct mtime

    index2 = CodeIndex(repo)
    index2.refresh()
    assert index2.get_doc("conf.json").top_keys == ["c"]


def test_refresh_removes_deleted_doc(repo: Path):
    index = CodeIndex(repo)
    index.build()
    (repo / "readme.md").unlink()

    index2 = CodeIndex(repo)
    index2.refresh()
    assert index2.get_doc("readme.md") is None
    assert "conf.json" in index2.all_docs()
