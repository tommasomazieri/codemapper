"""Tests for codemapper.docparser (light non-Python file parsing)."""
from pathlib import Path

from codemapper.docparser import DocFile, parse_doc, parse_docs

FIXTURES = Path(__file__).parent / "fixtures"


# ── JSON ────────────────────────────────────────────────────────────────────

def test_json_top_keys_sorted():
    doc = parse_doc(FIXTURES / "sample.json", FIXTURES)
    assert doc.kind == "json"
    assert doc.top_keys == ["name", "settings", "version"]
    assert doc.headings == []


def test_malformed_json_never_raises(tmp_path):
    bad = tmp_path / "broken.json"
    bad.write_text("{ not valid json", encoding="utf-8")
    doc = parse_doc(bad, tmp_path)
    assert doc.kind == "json"
    assert doc.top_keys == []


def test_json_array_top_level_has_no_keys(tmp_path):
    arr = tmp_path / "list.json"
    arr.write_text("[1, 2, 3]", encoding="utf-8")
    assert parse_doc(arr, tmp_path).top_keys == []


# ── TOML ────────────────────────────────────────────────────────────────────

def test_toml_top_keys():
    doc = parse_doc(FIXTURES / "sample.toml", FIXTURES)
    assert doc.kind == "toml"
    assert doc.top_keys == ["build-system", "project"]


# ── Markdown ────────────────────────────────────────────────────────────────

def test_markdown_headings_and_wikilinks():
    doc = parse_doc(FIXTURES / "sample.md", FIXTURES)
    assert doc.kind == "markdown"
    assert doc.headings == ["# Sample Doc", "## Details", "### Subsection"]
    # deduped, alias stripped, order preserved
    assert doc.wikilinks == ["other-doc", "notes"]


# ── Other / fallthrough ─────────────────────────────────────────────────────

def test_other_kind_lists_path_only(tmp_path):
    f = tmp_path / "data.bin"
    f.write_text("whatever", encoding="utf-8")
    doc = parse_doc(f, tmp_path)
    assert doc == DocFile(path="data.bin", kind="other")


# ── parse_docs (directory walk) ─────────────────────────────────────────────

def test_parse_docs_skips_py_and_cache(tmp_path):
    (tmp_path / "a.py").write_text("x = 1", encoding="utf-8")
    (tmp_path / "a.json").write_text('{"k": 1}', encoding="utf-8")
    (tmp_path / ".codemapper_cache.json").write_text("{}", encoding="utf-8")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "junk.json").write_text("{}", encoding="utf-8")

    docs = parse_docs(tmp_path)
    assert set(docs) == {"a.json"}
