"""Tests for codemapper.api grouped symbol format."""
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from codemapper.api import app

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def client():
    os.environ["CODEMAPPER_ROOT"] = str(FIXTURES_DIR)
    with TestClient(app) as c:
        yield c


# ── /map level 0 ───────────────────────────────────────────────────────────

def test_map_level0_has_module_doc(client):
    r = client.get("/map?level=0")
    assert r.status_code == 200
    data = r.json()
    sample_key = next(k for k in data["files"] if "sample_module" in k)
    entry = data["files"][sample_key]
    assert "module_doc" in entry
    assert "classes" not in entry
    assert "functions" not in entry


# ── /map level 1 ───────────────────────────────────────────────────────────

def test_map_level1_grouped_no_flat_symbols(client):
    r = client.get("/map?level=1")
    assert r.status_code == 200
    data = r.json()
    sample_key = next(k for k in data["files"] if "sample_module" in k)
    entry = data["files"][sample_key]
    assert "symbols" not in entry, "flat 'symbols' list should not appear at level 1"
    assert "classes" in entry


def test_map_level1_class_has_methods(client):
    r = client.get("/map?level=1")
    data = r.json()
    sample_key = next(k for k in data["files"] if "sample_module" in k)
    classes = data["files"][sample_key]["classes"]
    animal = next(c for c in classes if c["name"] == "Animal")
    method_names = {m["name"] for m in animal["methods"]}
    assert "speak" in method_names
    assert "_private" in method_names


def test_map_level1_no_signatures(client):
    r = client.get("/map?level=1")
    data = r.json()
    sample_key = next(k for k in data["files"] if "sample_module" in k)
    classes = data["files"][sample_key]["classes"]
    animal = next(c for c in classes if c["name"] == "Animal")
    for method in animal["methods"]:
        assert "signature" not in method


def test_map_level1_decorator_on_class(client):
    r = client.get("/map?level=1")
    data = r.json()
    sample_key = next(k for k in data["files"] if "sample_module" in k)
    classes = data["files"][sample_key]["classes"]
    animal = next(c for c in classes if c["name"] == "Animal")
    assert "@dataclass" in animal["decorators"]


def test_map_level1_decorator_on_method(client):
    r = client.get("/map?level=1")
    data = r.json()
    sample_key = next(k for k in data["files"] if "sample_module" in k)
    classes = data["files"][sample_key]["classes"]
    vehicle = next(c for c in classes if c["name"] == "Vehicle")
    from_dict = next(m for m in vehicle["methods"] if m["name"] == "from_dict")
    assert "@classmethod" in from_dict["decorators"]


# ── /map level 2 ───────────────────────────────────────────────────────────

def test_map_level2_has_signatures(client):
    r = client.get("/map?level=2")
    data = r.json()
    sample_key = next(k for k in data["files"] if "sample_module" in k)
    classes = data["files"][sample_key]["classes"]
    animal = next(c for c in classes if c["name"] == "Animal")
    speak = next(m for m in animal["methods"] if m["name"] == "speak")
    assert speak["signature"] == "speak(self) -> str"


def test_map_level2_function_signature(client):
    r = client.get("/map?level=2")
    data = r.json()
    sample_key = next(k for k in data["files"] if "sample_module" in k)
    functions = data["files"][sample_key]["functions"]
    fn = next(f for f in functions if f["name"] == "standalone_function")
    assert fn["signature"] == "standalone_function(x: int, y: float = 0.0) -> str"


# ── /file endpoint ─────────────────────────────────────────────────────────

def test_file_imports_split(client):
    r = client.get("/file/sample_module.py?level=2")
    assert r.status_code == 200
    data = r.json()
    assert "imports" in data
    assert "global" in data["imports"]
    assert "scoped" in data["imports"]


def test_file_global_imports(client):
    r = client.get("/file/sample_module.py?level=2")
    data = r.json()
    global_mods = {i["module"] for i in data["imports"]["global"]}
    assert "os" in global_mods
    assert "sys" in global_mods


def test_file_scoped_imports(client):
    r = client.get("/file/sample_module.py?level=2")
    data = r.json()
    scoped = data["imports"]["scoped"]
    assert any(i["module"] == "json" and i["scope"] == "lazy_loader" for i in scoped)


def test_file_variables_present(client):
    r = client.get("/file/sample_module.py?level=1")
    data = r.json()
    var_names = {v["name"] for v in data.get("variables", [])}
    assert "not_a_constant" in var_names


def test_file_no_flat_symbols(client):
    r = client.get("/file/sample_module.py?level=1")
    data = r.json()
    assert "symbols" not in data


# ── module_doc_full ─────────────────────────────────────────────────────────

def test_file_level0_no_full_doc(client):
    r = client.get("/file/sample_module.py?level=0")
    data = r.json()
    assert "module_doc_full" not in data


def test_file_level1_has_full_doc(client):
    r = client.get("/file/sample_module.py?level=1")
    data = r.json()
    assert data["module_doc"] == "Sample module for testing codemapper parser."
    assert "second line" in data["module_doc_full"]


# ── /docs and /doc ──────────────────────────────────────────────────────────

def test_docfiles_level0_kind_only(client):
    r = client.get("/docfiles?level=0")
    assert r.status_code == 200
    docs = r.json()["docs"]
    assert docs["sample.json"] == {"kind": "json"}
    assert "sample.md" in docs


def test_docfiles_level1_details(client):
    r = client.get("/docfiles?level=1")
    docs = r.json()["docs"]
    assert docs["sample.json"]["top_keys"] == ["name", "settings", "version"]
    assert docs["sample.md"]["headings"][0] == "# Sample Doc"
    assert docs["sample.md"]["wikilinks"] == ["other-doc", "notes"]


def test_doc_single(client):
    r = client.get("/doc/sample.toml")
    assert r.status_code == 200
    data = r.json()
    assert data["kind"] == "toml"
    assert data["top_keys"] == ["build-system", "project"]


def test_doc_not_found(client):
    assert client.get("/doc/nope.json").status_code == 404


# ── /map?include_docs ───────────────────────────────────────────────────────

def test_map_include_docs(client):
    r = client.get("/map?level=0&include_docs=true")
    data = r.json()
    assert "docs" in data
    assert data["docs"]["sample.json"] == {"kind": "json"}


def test_map_excludes_docs_by_default(client):
    r = client.get("/map?level=0")
    assert "docs" not in r.json()


# ── /staleness ──────────────────────────────────────────────────────────────

def test_staleness_shape(client):
    r = client.get("/staleness")
    assert r.status_code == 200
    data = r.json()
    assert data["threshold"] == 5
    assert isinstance(data["stale_count"], int)
    paths = {f["path"] for f in data["findings"]}
    assert "sample_module.py" in paths
    for f in data["findings"]:
        assert set(f) >= {"path", "has_docstring", "stale", "reason", "code_commits_since"}
