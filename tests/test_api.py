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
