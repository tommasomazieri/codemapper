"""Tests for multi-language diagnostics: language detection, the fallow JSON
adapter (fixture-driven, no binary needed), and the HTML tree-sitter pass."""

import textwrap
from pathlib import Path

import pytest

from codemapper.analysis import fallow_adapter
from codemapper.analysis.html import find_html_issues
from codemapper.languages import collect_files_by_language, detect_language


# --------------------------------------------------------------------------- #
# Language detection
# --------------------------------------------------------------------------- #

class TestLanguages:
    @pytest.mark.parametrize("path,lang", [
        ("a.py", "python"),
        ("src/x.ts", "typescript"),
        ("src/x.tsx", "typescript"),
        ("src/y.js", "javascript"),
        ("src/y.mjs", "javascript"),
        ("index.html", "html"),
        ("notes.md", None),
    ])
    def test_detect_language(self, path, lang):
        assert detect_language(path) == lang

    def test_collect_buckets_and_ignores(self, tmp_path):
        (tmp_path / "a.py").write_text("x = 1", encoding="utf-8")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "x.ts").write_text("export const x = 1", encoding="utf-8")
        (tmp_path / "page.html").write_text("<html></html>", encoding="utf-8")
        # ignored dirs
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "dep.js").write_text("// vendored", encoding="utf-8")

        buckets = collect_files_by_language(tmp_path)
        assert buckets["python"] == ["a.py"]
        assert buckets["typescript"] == ["src/x.ts"]
        assert buckets["html"] == ["page.html"]
        assert "javascript" not in buckets  # node_modules ignored


# --------------------------------------------------------------------------- #
# fallow JSON adapter (documented shapes — no subprocess)
# --------------------------------------------------------------------------- #

class TestFallowAdapter:
    def test_dead_code_export(self):
        data = {
            "entry_points": ["src/main.ts"],
            "findings": [{
                "path": "src/utils.ts", "export_name": "helperFn", "line": 10,
                "actions": [{"type": "remove-export", "auto_fixable": True,
                             "description": "Remove the unused export"}],
            }],
        }
        out = fallow_adapter._parse_dead(data, want_deps=True, want_dead=True)
        assert len(out) == 1
        f = out[0]
        assert f.rule == "dead_code"
        assert f.symbol == "helperFn"
        assert f.language == "typescript"
        assert f.line == 10
        assert f.actions[0].kind == "remove_symbol"
        assert f.actions[0].auto_fixable is True

    def test_dead_code_scope_excludes_deps(self):
        data = {"findings": [
            {"path": "a.ts", "export_name": "foo", "line": 1},
            {"path": "b.ts", "kind": "unused-dependency", "dependency": "lodash", "line": 2},
        ]}
        only_dead = fallow_adapter._parse_dead(data, want_deps=False, want_dead=True)
        assert {f.rule for f in only_dead} == {"dead_code"}
        only_deps = fallow_adapter._parse_dead(data, want_deps=True, want_dead=False)
        assert {f.rule for f in only_deps} == {"unused_dependency"}
        assert only_deps[0].symbol == "lodash"

    def test_health_complexity_severity(self):
        data = {"findings": [
            {"path": "src/diff/index.js", "name": "diff", "line": 48,
             "cyclomatic": 67, "cognitive": 138, "line_count": 290, "exceeded": "both"},
            {"path": "src/ok.js", "name": "small", "line": 3,
             "cyclomatic": 12, "cognitive": 4, "exceeded": "cyclomatic"},
        ]}
        out = fallow_adapter._parse_health(data, want_complexity=True, want_circular=False)
        big = next(f for f in out if f.symbol == "diff")
        assert big.rule == "high_complexity"
        assert big.severity == "error"
        assert big.language == "javascript"
        assert big.metadata == {"cyclomatic": 67, "cognitive": 138}
        small = next(f for f in out if f.symbol == "small")
        assert small.severity == "warn"

    def test_health_circular_count(self):
        data = {"vital_signs": {"circular_dep_count": 2}}
        out = fallow_adapter._parse_health(data, want_complexity=False, want_circular=True)
        assert len(out) == 1
        assert out[0].rule == "circular_dependency"

    def test_dupes(self):
        data = {"findings": [{
            "lines": 14,
            "occurrences": [{"path": "a.ts", "start_line": 5}, {"path": "b.ts", "start_line": 40}],
        }]}
        out = fallow_adapter._parse_dupes(data)
        assert len(out) == 2
        assert all(f.rule == "duplicate_code" for f in out)
        assert {f.path for f in out} == {"a.ts", "b.ts"}


# --------------------------------------------------------------------------- #
# HTML tree-sitter pass (skips if wheels absent)
# --------------------------------------------------------------------------- #

_HAS_TS = True
try:  # pragma: no cover
    import tree_sitter  # noqa: F401
    import tree_sitter_html  # noqa: F401
except ImportError:  # pragma: no cover
    _HAS_TS = False


@pytest.mark.skipif(not _HAS_TS, reason="tree-sitter-html not installed")
class TestHtml:
    def _write(self, tmp_path: Path, body: str) -> list[str]:
        (tmp_path / "index.html").write_text(textwrap.dedent(body), encoding="utf-8")
        return ["index.html"]

    def test_duplicate_id_and_missing_alt_and_lang(self, tmp_path):
        files = self._write(tmp_path, """
            <html>
              <body>
                <div id="main"></div>
                <div id="main"></div>
                <img src="logo.png">
              </body>
            </html>
        """)
        # logo.png exists so broken_local_ref does not fire here
        (tmp_path / "logo.png").write_bytes(b"x")
        rules = {(f.rule, f.symbol) for f in find_html_issues(tmp_path, files)}
        assert ("duplicate_id", "main") in rules
        assert any(r == "missing_alt" for r, _ in rules)
        assert any(r == "missing_lang" for r, _ in rules)

    def test_broken_local_ref(self, tmp_path):
        files = self._write(tmp_path, """
            <html lang="en">
              <head><link href="styles/app.css"></head>
              <body><a href="https://example.com">ok</a></body>
            </html>
        """)
        out = find_html_issues(tmp_path, files)
        broken = [f for f in out if f.rule == "broken_local_ref"]
        assert len(broken) == 1
        assert "styles/app.css" in broken[0].message

    def test_inline_script_loc(self, tmp_path):
        script = "\n".join(f"var v{i} = {i};" for i in range(60))
        files = self._write(tmp_path, f"<html lang='en'><body><script>\n{script}\n</script></body></html>")
        out = find_html_issues(tmp_path, files)
        assert any(f.rule == "inline_script_loc" for f in out)
