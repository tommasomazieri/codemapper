"""Tests for codemapper.analysis — dead code, complexity, deps, and orchestrator."""

import textwrap
from pathlib import Path

import pytest

from codemapper.analysis import ANALYZERS, analyze
from codemapper.analysis.complexity import find_complexity
from codemapper.analysis.deadcode import find_dead_code
from codemapper.analysis.deps import find_dependency_issues
from codemapper.index import CodeIndex


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build(tmp_path: Path, files: dict[str, str]) -> CodeIndex:
    for name, content in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(content), encoding="utf-8")
    index = CodeIndex(tmp_path)
    index.build()
    return index


# ---------------------------------------------------------------------------
# Dead-code analyzer
# ---------------------------------------------------------------------------

class TestDeadCode:
    def test_unreferenced_function_flagged(self, tmp_path):
        index = _build(tmp_path, {
            "a.py": """
                def used():
                    pass

                def old_helper():
                    pass

                used()
            """,
        })
        findings = find_dead_code(index, tmp_path)
        rules = {(f.rule, f.symbol) for f in findings}
        assert ("dead_code", "old_helper") in rules
        assert not any(f.symbol == "used" for f in findings if f.rule == "dead_code")

    def test_framework_decorator_not_flagged(self, tmp_path):
        index = _build(tmp_path, {
            "routes.py": """
                def handler():
                    pass

                class app:
                    @staticmethod
                    def get(path):
                        def dec(f): return f
                        return dec

                @app.get("/")
                def index():
                    pass
            """,
        })
        findings = find_dead_code(index, tmp_path)
        assert not any(f.symbol == "index" for f in findings if f.rule == "dead_code")

    def test_all_export_not_flagged(self, tmp_path):
        index = _build(tmp_path, {
            "lib.py": """
                __all__ = ["exported"]

                def exported():
                    pass

                def internal():
                    pass
            """,
        })
        findings = find_dead_code(index, tmp_path)
        dead_syms = {f.symbol for f in findings if f.rule == "dead_code"}
        assert "exported" not in dead_syms

    def test_dead_file_unimported_module(self, tmp_path):
        index = _build(tmp_path, {
            "main.py": "x = 1",
            "unused_mod.py": "def helper(): pass",
        })
        findings = find_dead_code(index, tmp_path)
        dead_files = {f.path for f in findings if f.rule == "dead_file"}
        assert "unused_mod.py" in dead_files
        # main is an always-live name, should not be flagged
        assert "main.py" not in dead_files

    def test_init_not_dead_file(self, tmp_path):
        index = _build(tmp_path, {
            "pkg/__init__.py": "from pkg.mod import thing",
            "pkg/mod.py": "def thing(): pass",
        })
        findings = find_dead_code(index, tmp_path)
        dead_files = {f.path for f in findings if f.rule == "dead_file"}
        assert "pkg/__init__.py" not in dead_files

    def test_test_file_not_flagged(self, tmp_path):
        index = _build(tmp_path, {
            "tests/test_foo.py": """
                def test_something():
                    assert True
            """,
        })
        findings = find_dead_code(index, tmp_path)
        dead_syms = {f.symbol for f in findings if f.rule == "dead_code"}
        assert "test_something" not in dead_syms
        dead_files = {f.path for f in findings if f.rule == "dead_file"}
        assert not any("test_foo" in p for p in dead_files)

    def test_dead_code_action_is_remove_symbol(self, tmp_path):
        index = _build(tmp_path, {
            "a.py": "def ghost(): pass",
        })
        findings = find_dead_code(index, tmp_path)
        dc = next((f for f in findings if f.rule == "dead_code" and f.symbol == "ghost"), None)
        assert dc is not None
        assert dc.actions[0].kind == "remove_symbol"
        assert dc.actions[0].auto_fixable is True


# ---------------------------------------------------------------------------
# Complexity analyzer
# ---------------------------------------------------------------------------

class TestComplexity:
    def _complex_function(self) -> str:
        """A function designed to exceed cc_warn=10."""
        return textwrap.dedent("""
            def tangled(x, y, z):
                if x > 0:
                    if y > 0:
                        if z > 0:
                            return x + y + z
                        elif z == 0:
                            return x + y
                        else:
                            return x
                    elif y < 0:
                        for i in range(x):
                            if i % 2 == 0:
                                z += i
                            else:
                                z -= i
                        return z
                    else:
                        while x > 0:
                            x -= 1
                            if x == 5:
                                break
                        return x
                elif x < 0:
                    try:
                        return 1 / x
                    except ZeroDivisionError:
                        return 0
                else:
                    return y and z or x
        """)

    def test_complex_function_flagged(self, tmp_path):
        index = _build(tmp_path, {"mod.py": self._complex_function()})
        findings = find_complexity(index, tmp_path, cc_warn=10)
        assert any(f.rule == "high_complexity" and f.symbol == "tangled" for f in findings)

    def test_metadata_has_cyclomatic_and_cognitive(self, tmp_path):
        index = _build(tmp_path, {"mod.py": self._complex_function()})
        findings = find_complexity(index, tmp_path, cc_warn=10)
        f = next(f for f in findings if f.symbol == "tangled")
        assert "cyclomatic" in f.metadata
        assert "cognitive" in f.metadata
        assert f.metadata["cyclomatic"] >= 10

    def test_simple_function_not_flagged(self, tmp_path):
        index = _build(tmp_path, {
            "mod.py": "def simple(x): return x + 1",
        })
        findings = find_complexity(index, tmp_path)
        assert not findings

    def test_error_severity_above_cc_error(self, tmp_path):
        # Build a very deeply nested function to exceed cc_error=20
        branches = "\n".join(
            "    " * (i + 1) + f"if x > {i}:" for i in range(22)
        )
        code = f"def mega(x):\n{branches}\n{'    ' * 23}return x\n"
        index = _build(tmp_path, {"mod.py": code})
        findings = find_complexity(index, tmp_path, cc_warn=10, cc_error=20)
        errors = [f for f in findings if f.rule == "high_complexity" and f.severity == "error"]
        assert errors

    def test_action_is_refactor_split_not_auto_fixable(self, tmp_path):
        index = _build(tmp_path, {"mod.py": self._complex_function()})
        findings = find_complexity(index, tmp_path, cc_warn=10)
        f = next(f for f in findings if f.symbol == "tangled")
        assert f.actions[0].kind == "refactor_split"
        assert f.actions[0].auto_fixable is False

    def test_method_qualname(self, tmp_path):
        code = textwrap.dedent("""
            class MyClass:
                def complex_method(self, x):
                    if x > 0:
                        for i in range(x):
                            if i % 2 == 0:
                                if i > 5:
                                    if i > 10:
                                        if i > 15:
                                            return i
                    return 0
        """)
        index = _build(tmp_path, {"mod.py": code})
        findings = find_complexity(index, tmp_path, cc_warn=5)
        assert any("MyClass.complex_method" in f.symbol for f in findings)


# ---------------------------------------------------------------------------
# Dependency hygiene analyzer
# ---------------------------------------------------------------------------

class TestDeps:
    def test_unused_import_flagged(self, tmp_path):
        index = _build(tmp_path, {
            "mod.py": "import os\nimport sys\nx = sys.argv\n",
        })
        findings = find_dependency_issues(index, tmp_path)
        unused = {f.symbol for f in findings if f.rule == "unused_import"}
        assert "os" in unused
        assert "sys" not in unused

    def test_noqa_skips_unused_import(self, tmp_path):
        index = _build(tmp_path, {
            "mod.py": "import os  # noqa\nx = 1\n",
        })
        findings = find_dependency_issues(index, tmp_path)
        unused = {f.symbol for f in findings if f.rule == "unused_import"}
        assert "os" not in unused

    def test_init_py_unused_imports_skipped(self, tmp_path):
        index = _build(tmp_path, {
            "pkg/__init__.py": "from pkg.core import MyClass\n",
            "pkg/core.py": "class MyClass: pass\n",
        })
        findings = find_dependency_issues(index, tmp_path)
        unused = [f for f in findings if f.rule == "unused_import"]
        assert not unused

    def test_unused_declared_dependency(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            '[project]\ndependencies = ["requests>=2", "httpx"]\n',
            encoding="utf-8",
        )
        index = _build(tmp_path, {
            "mod.py": "import requests\nx = requests.get('/')\n",
        })
        findings = find_dependency_issues(index, tmp_path)
        unused_deps = {f.symbol for f in findings if f.rule == "unused_dependency"}
        assert "httpx" in unused_deps
        assert "requests" not in unused_deps

    def test_undeclared_dependency(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            "[project]\ndependencies = []\n",
            encoding="utf-8",
        )
        index = _build(tmp_path, {
            "mod.py": "import requests\n",
        })
        findings = find_dependency_issues(index, tmp_path)
        undeclared = {f.symbol for f in findings if f.rule == "undeclared_dependency"}
        assert "requests" in undeclared

    def test_unresolved_local_import(self, tmp_path):
        index = _build(tmp_path, {
            "mod.py": "from mypackage.ghost import Phantom\n",
        })
        # Manually mark the import as local in the index (simulate misclassification)
        # In practice, parse_repo classifies based on local_stems. We write a file that
        # imports from a module that doesn't exist in the repo but starts with a local stem.
        # Easier: build with a file that references itself as a local module.
        (tmp_path / "mypackage").mkdir()
        (tmp_path / "mypackage" / "__init__.py").write_text("", encoding="utf-8")
        index2 = CodeIndex(tmp_path)
        index2.build()
        # mypackage.ghost would be local (mypackage stem exists) but ghost.py doesn't
        findings2 = find_dependency_issues(index2, tmp_path)
        unresolved = {f.symbol for f in findings2 if f.rule == "unresolved_import"}
        assert "mypackage.ghost" in unresolved

    def test_unused_import_action_auto_fixable(self, tmp_path):
        index = _build(tmp_path, {
            "mod.py": "import os\nx = 1\n",
        })
        findings = find_dependency_issues(index, tmp_path)
        f = next(f for f in findings if f.rule == "unused_import" and f.symbol == "os")
        assert f.actions[0].kind == "remove_import"
        assert f.actions[0].auto_fixable is True

    def test_unused_dependency_action_auto_fixable(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text(
            "[project]\ndependencies = [\"rich\"]\n",
            encoding="utf-8",
        )
        index = _build(tmp_path, {"mod.py": "x = 1\n"})
        findings = find_dependency_issues(index, tmp_path)
        f = next((f for f in findings if f.rule == "unused_dependency"), None)
        assert f is not None
        assert f.actions[0].auto_fixable is True


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class TestOrchestrator:
    def test_scope_filters_analyzers(self, tmp_path):
        index = _build(tmp_path, {
            "mod.py": "import os\ndef ghost(): pass\nx = 1\n",
        })
        # Only deps — no dead_code findings
        result = analyze(index, tmp_path, scope=["deps"])
        assert result.scope == ["deps"]
        assert not any(f.rule == "dead_code" for f in result.findings)
        # Only dead — no unused_import findings
        result2 = analyze(index, tmp_path, scope=["dead"])
        assert not any(f.rule == "unused_import" for f in result2.findings)

    def test_summary_counts_correct(self, tmp_path):
        index = _build(tmp_path, {
            "mod.py": "import os\ndef ghost(): pass\nx = 1\n",
        })
        result = analyze(index, tmp_path, scope=["dead", "deps"])
        total = sum(result.summary["by_rule"].values())
        assert total == result.summary["total"] == len(result.findings)

    def test_score_perfect_when_clean(self, tmp_path):
        index = _build(tmp_path, {
            "mod.py": "def add(x, y): return x + y\n",
        })
        result = analyze(index, tmp_path, scope=["complexity"])
        assert result.score == 100

    def test_score_degrades_with_findings(self, tmp_path):
        # Multiple warn findings should reduce score
        code = "\n".join(f"import mod{i}" for i in range(20))
        index = _build(tmp_path, {"mod.py": code})
        result = analyze(index, tmp_path, scope=["deps"])
        assert result.score < 100

    def test_findings_sorted_by_path_line_rule(self, tmp_path):
        index = _build(tmp_path, {
            "a.py": "import os\nimport sys\nx = 1\n",
            "b.py": "import json\ny = 2\n",
        })
        result = analyze(index, tmp_path, scope=["deps"])
        paths = [f.path for f in result.findings if f.rule == "unused_import"]
        assert paths == sorted(paths)

    def test_all_analyzers_in_registry(self):
        assert set(ANALYZERS) == {"dead", "complexity", "deps"}

    def test_unknown_scope_item_ignored(self, tmp_path):
        index = _build(tmp_path, {"mod.py": "x = 1\n"})
        result = analyze(index, tmp_path, scope=["nonexistent"])
        assert result.findings == []
