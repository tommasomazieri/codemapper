"""Tests for codemapper.parser."""
from pathlib import Path

import pytest

from codemapper.parser import parse_file, parse_repo

FIXTURE = Path(__file__).parent / "fixtures" / "sample_module.py"


@pytest.fixture(scope="module")
def pf():
    return parse_file(FIXTURE, FIXTURE.parent.parent)


def _sym(pf, name):
    return next(s for s in pf.symbols if s.name == name)


# ── module_doc ─────────────────────────────────────────────────────────────

def test_module_doc_first_line(pf):
    assert pf.module_doc == "Sample module for testing codemapper parser."


# ── constants & variables ──────────────────────────────────────────────────

def test_constants_detected(pf):
    names = {s.name for s in pf.symbols if s.kind == "constant"}
    assert "CONSTANT_A" in names
    assert "CONSTANT_B" in names


def test_variable_detected(pf):
    names = {s.name for s in pf.symbols if s.kind == "variable"}
    assert "not_a_constant" in names


def test_constant_not_variable(pf):
    kinds = {s.name: s.kind for s in pf.symbols}
    assert kinds["CONSTANT_A"] == "constant"
    assert kinds["CONSTANT_B"] == "constant"


# ── classes ────────────────────────────────────────────────────────────────

def test_class_detected(pf):
    kinds = {s.name for s in pf.symbols if s.kind == "class"}
    assert "Animal" in kinds
    assert "Vehicle" in kinds


def test_class_decorator(pf):
    animal = _sym(pf, "Animal")
    assert "@dataclass" in animal.decorators


def test_class_no_decorator(pf):
    vehicle = _sym(pf, "Vehicle")
    assert vehicle.decorators == []


# ── methods ────────────────────────────────────────────────────────────────

def test_method_parent(pf):
    speak = _sym(pf, "speak")
    assert speak.parent == "Animal"
    assert speak.kind == "method"


def test_method_decorator(pf):
    from_dict = _sym(pf, "from_dict")
    assert "@classmethod" in from_dict.decorators


def test_method_no_decorator(pf):
    speak = _sym(pf, "speak")
    assert speak.decorators == []


def test_method_signature(pf):
    speak = _sym(pf, "speak")
    assert speak.signature == "speak(self) -> str"


# ── functions ──────────────────────────────────────────────────────────────

def test_standalone_function(pf):
    fn = _sym(pf, "standalone_function")
    assert fn.kind == "function"
    assert fn.parent is None
    assert fn.signature == "standalone_function(x: int, y: float = 0.0) -> str"


def test_async_function(pf):
    fn = _sym(pf, "async_func")
    assert fn.kind == "function"
    assert fn.signature == "async_func(items: list[str]) -> None"


# ── imports ────────────────────────────────────────────────────────────────

def test_global_imports_have_no_scope(pf):
    global_imps = [i for i in pf.imports if i.scope is None]
    modules = {i.module for i in global_imps}
    assert "os" in modules
    assert "sys" in modules


def test_scoped_import_captured(pf):
    scoped = [i for i in pf.imports if i.scope is not None]
    assert any(i.module == "json" and i.scope == "lazy_loader" for i in scoped)


def test_relative_import_kind(pf):
    rel = [i for i in pf.imports if i.alias == "utils"]
    assert rel, "relative import 'utils' not found"
    assert rel[0].kind == "local"


def test_stdlib_and_package_classification():
    # classification requires parse_repo — not available via parse_file alone
    repo = parse_repo(FIXTURE.parent.parent)
    sample = repo["fixtures/sample_module.py"]
    os_imp = next(i for i in sample.imports if i.module == "os" and i.scope is None)
    assert os_imp.kind == "stdlib"
    req_imp = next(i for i in sample.imports if i.module == "requests")
    assert req_imp.kind == "package"
